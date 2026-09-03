"""Audit seam for the credential gateway.

Resolution happens on every agent tool call, so this is a hot path. The sink is a seam
rather than a direct write: today it emits a structured log line and a counter, and the
buffering/disk-spool implementation that has to survive an ingest outage replaces it
without changing any call site.

Lifecycle events (issue, revoke) are low-volume and security-relevant; resolution events
are high-volume and operational. Both go through here so one implementation change
covers both.

Nothing in this module may log a token value. Callers pass identifiers only.
"""

import enum
import logging
from dataclasses import dataclass
from uuid import UUID

from prometheus_client import Counter

from api.domains.agents.models import SecretProvider

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


@dataclass(frozen=True)
class GatewayAuditSink:
    """Default sink: structured log plus counter."""

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
