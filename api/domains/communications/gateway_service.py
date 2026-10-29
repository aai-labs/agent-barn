import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject, singleton
from redis.exceptions import RedisError

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.addressing import extract_local_part
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.email_address_repository import AgentEmailAddressRepository
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    CommunicationConnection,
    CommunicationJournalStage,
    CommunicationPolicyDisposition,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
    RuntimeReplyCreate,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.plugins.base import (
    GatewayDeliveryPlugin,
    InboundAdmissionResult,
    PlatformSettings,
)
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.communications.transport import require_gateway_transport
from api.infrastructure.communication_signals import (
    CommunicationSignal,
    CommunicationSignalBus,
    CommunicationSignalType,
)
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class CommunicationsGatewayService:
    config: Config
    agent_repository: AgentRepository
    delivery_repository: CommunicationDeliveryRepository
    connection_repository: CommunicationConnectionRepository
    email_addresses: AgentEmailAddressRepository
    plugins: PlatformPluginRegistry
    signals: CommunicationSignalBus
    operations: CommunicationOperationalRepository | None = None

    def accept_inbound(
        self,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
    ) -> AcceptedCommunicationRead:
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled:
            raise LookupError("Communication Connection is unavailable")
        require_gateway_transport(connection.platform_key)
        accepted = self.delivery_repository.accept_inbound(
            connection_id=connection_id,
            envelope=envelope,
        )
        connection = self.connection_repository.get_active(connection_id)
        if connection is not None:
            self._publish_signal(
                connection.agent_id,
                CommunicationSignal(
                    type=CommunicationSignalType.DELIVERY_AVAILABLE,
                    delivery_id=accepted.delivery_id,
                ),
            )
        return accepted

    def authenticate_runtime(self, agent_id: UUID, provided_key: str) -> Agent:
        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None or agent.deleted_at is not None:
            raise PermissionError("Agent not found")
        if not agent.communication_key_encrypted:
            raise PermissionError("Agent has no Communication Runtime credential")
        stored_key = decrypt_token(
            agent.communication_key_encrypted,
            self.config.agent_token_encryption_key,
        )
        if not secrets.compare_digest(stored_key, provided_key):
            raise PermissionError("Invalid Communication Runtime credential")
        return agent

    async def stream_runtime_control(self, agent: Agent) -> AsyncIterator[str]:
        """Replay durable work, then asynchronously block on Redis wakeups."""
        cursor = await self.signals.latest_cursor_async(agent.id)
        yield f"data: {CommunicationSignal(type=CommunicationSignalType.DELIVERY_AVAILABLE).as_json()}\n\n"
        while True:
            cursor, signals = await self.signals.wait_async(agent.id, cursor)
            if not signals:
                yield ": keep-alive\n\n"
                continue
            for signal in signals:
                yield f"data: {signal.as_json()}\n\n"

    def claim_runtime_delivery(self, agent: Agent) -> RuntimeDeliveryRead | None:
        if agent.status != AgentStatus.RUNNING:
            raise RuntimeError("Agent is not running")
        self.delivery_repository.reclaim_expired_inbound(
            agent_id=agent.id,
        )
        delivery = self.delivery_repository.claim_next_inbound(
            agent_id=agent.id,
            reclaim_expired=False,
        )
        if delivery is not None:
            delivery = self._for_runtime(delivery)
        return delivery

    def _for_runtime(self, delivery: RuntimeDeliveryRead) -> RuntimeDeliveryRead:
        connection = self.connection_repository.get_active(delivery.connection_id)
        if connection is None:
            raise RuntimeError(f"Connection {delivery.connection_id} is no longer active")
        try:
            plugin = self.plugins.require_delivery(connection.platform_key)
            prompt = plugin.runtime_prompt(delivery.envelope)
        except Exception as exc:
            raise RuntimeError(f"Could not prepare runtime delivery for Connection {delivery.connection_id}") from exc
        return delivery.model_copy(
            update={
                "progress_updates": plugin.supports_progress_updates,
                "envelope": delivery.envelope.model_copy(update={"text": prompt}),
            }
        )

    def find_active_inbound_delivery(
        self,
        connection_id: UUID,
        location: ConversationLocation,
    ) -> UUID | None:
        return self.delivery_repository.find_active_inbound_delivery(
            connection_id=connection_id,
            ordering_key=self.delivery_repository.ordering_key_for_location(connection_id, location),
        )

    def request_cancel_delivery(self, agent_id: UUID, delivery_id: UUID) -> bool:
        """Persist cancellation before waking the Agent's outbound control stream."""
        delivery_status = self.delivery_repository.request_cancel(delivery_id, agent_id=agent_id)
        if delivery_status is None:
            return False
        self._publish_signal(
            agent_id,
            CommunicationSignal(
                type=CommunicationSignalType.DELIVERY_CANCELLED,
                delivery_id=delivery_id,
            ),
        )
        return True

    def _publish_signal(self, agent_id: UUID, signal: CommunicationSignal) -> None:
        try:
            self.signals.publish(agent_id, signal)
        except RedisError as exc:
            # PostgreSQL is authoritative. A runtime/browser reconnect takes a
            # stream cursor before replaying durable state, so notification
            # failure must not roll back an accepted message or cancellation.
            logger.warning(
                "Communication signal publish failed for Agent %s (%s)",
                agent_id,
                type(exc).__name__,
            )

    def complete_runtime_delivery(
        self,
        agent: Agent,
        delivery_id: UUID,
        result: RuntimeDeliveryResult,
    ) -> bool:
        normalized_error = (
            normalize_communication_error(
                error_code=result.error_code,
                error_message=result.error_message,
                operation="runtime_processing",
            )
            if not result.succeeded
            else None
        )
        completed = self.delivery_repository.complete_runtime_delivery(
            delivery_id,
            agent_id=agent.id,
            succeeded=result.succeeded,
            error_code=normalized_error.code if normalized_error is not None else None,
            error_message=normalized_error.summary if normalized_error is not None else None,
            error_details=normalized_error.details if normalized_error is not None else None,
        )
        if completed:
            # A successful completion also enqueues a reply, which publishes
            # its own signal — but a failed/cancelled delivery ends here with
            # no reply, so this is the only wakeup a waiting Web Chat stream
            # ever gets for its terminal status.
            self._publish_signal(
                agent.id,
                CommunicationSignal(type=CommunicationSignalType.MESSAGE_CHANGED, delivery_id=delivery_id),
            )
        return completed

    def renew_runtime_delivery_lease(
        self,
        agent: Agent,
        delivery_id: UUID,
        *,
        awaiting_input: bool = False,
    ) -> bool:
        if agent.status != AgentStatus.RUNNING:
            raise RuntimeError("Agent is not running")
        return self.delivery_repository.renew_runtime_delivery_lease(
            delivery_id,
            agent_id=agent.id,
            awaiting_input=awaiting_input,
        )

    def enqueue_runtime_reply(
        self,
        agent: Agent,
        source_delivery_id: UUID,
        reply: RuntimeReplyCreate,
    ) -> UUID:
        delivery_id = self.delivery_repository.enqueue_runtime_reply(
            agent_id=agent.id,
            source_delivery_id=source_delivery_id,
            reply=reply,
        )
        self._publish_signal(
            agent.id,
            CommunicationSignal(
                type=CommunicationSignalType.MESSAGE_CHANGED,
                delivery_id=delivery_id,
            ),
        )
        return delivery_id

    def _accept_admitted_payload(
        self,
        connection: CommunicationConnection,
        plugin: GatewayDeliveryPlugin,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> list[AcceptedCommunicationRead]:
        self._record_journal(
            connection,
            CommunicationJournalStage.PROVIDER_OBSERVED,
        )
        admission = self._admit_plugin_payload(connection.id, plugin, settings, payload)
        # Only accepted events reach the POLICY_ADMITTED stage; rejected events
        # record their own stage so the pipeline funnel can show drop-off
        # instead of always equating provider_observed with policy_admitted.
        self._record_journal(
            connection,
            CommunicationJournalStage.POLICY_ADMITTED
            if admission.disposition == CommunicationPolicyDisposition.ACCEPTED
            else CommunicationJournalStage.POLICY_REJECTED,
            disposition=admission.disposition,
        )
        self._record_policy_metric(admission.disposition)
        if admission.disposition != CommunicationPolicyDisposition.ACCEPTED:
            return []
        envelopes = list(admission)
        accepted: list[AcceptedCommunicationRead] = []
        for envelope in envelopes:
            result = self.accept_inbound(connection.id, envelope)
            accepted.append(result)
        return accepted

    def _admit_plugin_payload(
        self,
        connection_id: UUID,
        plugin: GatewayDeliveryPlugin,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        try:
            result = plugin.normalize_inbound(settings, payload)
        except Exception as exc:
            logger.warning(
                "Communication payload admission failed for Connection %s (%s)",
                connection_id,
                type(exc).__name__,
            )
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if not isinstance(result, InboundAdmissionResult):
            raise TypeError("Communication plugin returned an unsupported admission result")
        return result

    def _record_journal(
        self,
        connection: CommunicationConnection,
        stage: CommunicationJournalStage,
        *,
        disposition: CommunicationPolicyDisposition | None = None,
    ) -> None:
        if self.operations is None:
            return
        organization_id = getattr(connection, "organization_id", None)
        agent_id = getattr(connection, "agent_id", None)
        if organization_id is None or agent_id is None:
            return
        try:
            self.operations.record_journal(
                organization_id=organization_id,
                agent_id=agent_id,
                connection_id=connection.id,
                stage=stage,
                disposition=disposition,
            )
        except Exception as exc:
            # Provider observation and policy admission are observability, not
            # ingress: a diagnostics-table failure must not drop or 500 a real
            # provider message (polling transports cannot replay a consumed
            # payload, so failing closed would lose it permanently).
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

    def accept_email_inbound(
        self,
        payload: dict[str, Any],
        authorization: str,
    ) -> list[AcceptedCommunicationRead]:
        """Accept one parsed inbound message from the email ingress Worker.

        Authenticated by a gateway-level shared secret rather than the
        per-Connection driver key: the Worker is addressed by mailbox and knows
        only the recipient address, never a Connection id. An address that does
        not resolve returns an empty acceptance rather than an error, so the
        endpoint cannot be used to enumerate which agent addresses exist.
        """
        secret = self.config.email_inbound_secret.strip()
        provided = authorization.removeprefix("Bearer ").strip()
        if not secret or not secrets.compare_digest(secret, provided):
            raise PermissionError("Invalid email ingress credential")

        local_part = extract_local_part(self.config.agent_email_mailbox, str(payload.get("to") or ""))
        if not local_part:
            return []
        connection_id = self.email_addresses.resolve(local_part)
        if connection_id is None:
            return []
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled or connection.platform_key != "email":
            return []
        plugin = self.plugins.require_delivery("email")
        settings = plugin.settings_model.model_validate(connection.settings)
        return self._accept_admitted_payload(connection, plugin, settings, payload)
