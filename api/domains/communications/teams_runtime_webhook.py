"""API-owned public ingress for runtime-owned Microsoft Teams transport."""

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import CommunicationJournalStage, CommunicationPolicyDisposition
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.plugins.base import WebhookRequest
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.teams import TeamsPlatformPlugin, TeamsSettings
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.http import resilient_request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeWebhookRelayResponse:
    status_code: int
    body: bytes
    content_type: str | None = None


class RuntimeWebhookUnavailable(RuntimeError):
    pass


@inject
@singleton
@dataclass
class TeamsRuntimeWebhookRelay:
    """Authenticate, admit, and relay runtime-owned Teams traffic from the API edge."""

    config: Config
    agent_repository: AgentRepository
    connection_repository: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry
    operations: CommunicationOperationalRepository | None = None

    def relay(
        self,
        connection_id: UUID,
        payload: dict[str, Any],
        authorization: str,
    ) -> RuntimeWebhookRelayResponse | None:
        """Return None when this Connection remains gateway-owned for rollback."""
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled:
            raise PermissionError("Communication Connection not found")
        if connection.platform_key != "teams" or "teams" not in self.config.native_platform_keys:
            return None

        plugin = self.plugins.require("teams")
        if not isinstance(plugin, TeamsPlatformPlugin):
            raise TypeError("The Teams Platform Plugin is unavailable")
        credentials = plugin.credentials_model.model_validate(
            json.loads(decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key))
        )
        plugin.verify_webhook(
            credentials,
            WebhookRequest(
                raw_body=json.dumps(payload, separators=(",", ":")).encode(),
                payload=payload,
                authorization=authorization,
                headers={"Authorization": authorization},
            ),
        )
        settings = plugin.settings_model.model_validate(connection.settings)
        assert isinstance(settings, TeamsSettings)

        self._record_journal(connection, CommunicationJournalStage.PROVIDER_OBSERVED)
        disposition = plugin.runtime_relay_disposition(settings, payload)
        self._record_journal(
            connection,
            CommunicationJournalStage.POLICY_ADMITTED
            if disposition == CommunicationPolicyDisposition.ACCEPTED
            else CommunicationJournalStage.POLICY_REJECTED,
            disposition=disposition,
        )
        self._record_policy_metric(disposition)
        if disposition != CommunicationPolicyDisposition.ACCEPTED:
            return RuntimeWebhookRelayResponse(status_code=200, body=b"")

        agent = self.agent_repository.get_by_id(connection.agent_id)
        if agent is None or agent.deleted_at is not None or agent.status != AgentStatus.RUNNING:
            raise RuntimeWebhookUnavailable("Teams Agent runtime is not running")
        target = self.config.teams_runtime_webhook_url.format(
            agent_id=connection.agent_id, namespace=self.config.k8s_namespace
        )
        try:
            response = resilient_request(
                "POST",
                target,
                headers={"Authorization": authorization, "Content-Type": "application/json"},
                content=json.dumps(payload, separators=(",", ":")).encode(),
                timeout=10,
                max_retries=0,
                label="Teams runtime webhook relay",
            )
        except httpx.TransportError as exc:
            raise RuntimeWebhookUnavailable("Teams Agent runtime webhook is unavailable") from exc
        return RuntimeWebhookRelayResponse(
            status_code=response.status_code,
            body=response.content,
            content_type=response.headers.get("Content-Type"),
        )

    def _record_journal(
        self,
        connection: Any,
        stage: CommunicationJournalStage,
        *,
        disposition: CommunicationPolicyDisposition | None = None,
    ) -> None:
        if self.operations is None:
            return
        try:
            self.operations.record_journal(
                organization_id=connection.organization_id,
                agent_id=connection.agent_id,
                connection_id=connection.id,
                stage=stage,
                disposition=disposition,
            )
        except Exception as exc:
            logger.error(
                "Unable to record %s for Communication Connection %s (%s)",
                stage.value,
                connection.id,
                type(exc).__name__,
            )

    @staticmethod
    def _record_policy_metric(disposition: CommunicationPolicyDisposition) -> None:
        from api.domains.communications.metrics import record_policy_disposition

        record_policy_disposition(disposition)
