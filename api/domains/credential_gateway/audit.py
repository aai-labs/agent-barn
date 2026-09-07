"""Audit seam for the credential gateway.

Resolution happens on every agent tool call, so this is a hot path. Every event gets a
structured log line and a counter, plus a durable row in ``gateway_audit_event`` — no
buffering or disk spool, because the row is written through the same Postgres that
resolution itself already depends on (``GatewayTokenRepository.find_active_by_hash``,
``touch_last_used``). If Postgres is down, resolution already fails before an audit
event would be recorded, so there is no separate "ingest" that can be down while
resolution succeeds. The row write is best-effort like ``touch_last_used``: a failure to
persist it never turns a valid resolution into a failed one.

Lifecycle events (issue, revoke) are low-volume and security-relevant; resolution events
are high-volume and operational. Both go through here so one implementation change
covers both.

Nothing in this module may log a token value. Callers pass identifiers only.
"""

import enum
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from prometheus_client import Counter

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.models import GatewayAuditEvent
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger("api.credential_gateway.audit")

GATEWAY_TOKEN_RESOLUTIONS = Counter(
    "agentbarn_gateway_token_resolutions_total",
    "Gateway token resolution attempts by outcome.",
    ["outcome", "provider"],
)

GATEWAY_TOKEN_LIFECYCLE = Counter(
    "agentbarn_gateway_token_lifecycle_total",
    "Gateway token lifecycle transitions.",
    ["action", "provider"],
)


class ResolutionOutcome(str, enum.Enum):
    RESOLVED = "resolved"
    #: Presented token matches no row at all.
    UNKNOWN = "unknown"
    #: Matched a row that has been revoked. Distinguished from UNKNOWN because a spike
    #: means an agent is still running with a credential someone withdrew.
    REVOKED = "revoked"
    #: Header missing or not a bearer token.
    MALFORMED = "malformed"


@inject
@singleton
@dataclass(frozen=True)
class GatewayAuditSink:
    """Default sink: structured log, counter, and a durable Postgres row."""

    delegate: PostgresRepositoryDelegate

    def record_resolution(
        self,
        outcome: ResolutionOutcome,
        *,
        provider: SecretProvider | None = None,
        agent_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> None:
        label = provider.value if provider is not None else "unknown"
        GATEWAY_TOKEN_RESOLUTIONS.labels(outcome=outcome.value, provider=label).inc()
        logger.info(
            "gateway token resolution",
            extra={
                "outcome": outcome.value,
                "provider": label,
                "agent_id": str(agent_id) if agent_id else None,
                "organization_id": str(organization_id) if organization_id else None,
            },
        )
        self._save(
            GatewayAuditEvent(
                kind="resolution",
                detail=outcome.value,
                provider=provider.value if provider is not None else None,
                agent_id=agent_id,
                organization_id=organization_id,
            )
        )

    def record_lifecycle(
        self,
        action: str,
        *,
        provider: SecretProvider,
        agent_id: UUID,
        organization_id: UUID,
    ) -> None:
        GATEWAY_TOKEN_LIFECYCLE.labels(action=action, provider=provider.value).inc()
        logger.info(
            "gateway token %s",
            action,
            extra={
                "action": action,
                "provider": provider.value,
                "agent_id": str(agent_id),
                "organization_id": str(organization_id),
            },
        )
        self._save(
            GatewayAuditEvent(
                kind="lifecycle",
                detail=action,
                provider=provider.value,
                agent_id=agent_id,
                organization_id=organization_id,
            )
        )

    def _save(self, event: GatewayAuditEvent) -> None:
        """Best-effort, like ``GatewayTokenRepository.touch_last_used``.

        Never gates authorization: an audit-row write failure must not turn a valid
        resolution into a failed one.
        """
        try:
            self.delegate.save(event)
        except Exception:
            logger.exception("failed to persist gateway audit event")
