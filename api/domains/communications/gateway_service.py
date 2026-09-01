import json
import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject, singleton
from redis.exceptions import RedisError

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    CommunicationConnection,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationJournalStage,
    CommunicationPolicyDisposition,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    PlatformCapability,
    ProcessingFeedbackStage,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
    RuntimeReplyCreate,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.plugins.base import (
    InboundAdmissionContext,
    InboundAdmissionResult,
    PlatformPlugin,
    PlatformSettings,
    ProcessingFeedbackContext,
)
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
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
    plugins: PlatformPluginRegistry
    signals: CommunicationSignalBus
    operations: CommunicationOperationalRepository | None = None

    def accept_inbound(
        self,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
    ) -> AcceptedCommunicationRead:
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

    def stream_runtime_control(self, agent: Agent) -> Iterator[str]:
        """Replay durable work, then block on Redis control wakeups."""
        cursor = self.signals.latest_cursor(agent.id)
        yield f"data: {CommunicationSignal(type=CommunicationSignalType.DELIVERY_AVAILABLE).as_json()}\n\n"
        while True:
            cursor, signals = self.signals.wait(agent.id, cursor)
            if not signals:
                yield ": keep-alive\n\n"
                continue
            for signal in signals:
                yield f"data: {signal.as_json()}\n\n"

    def claim_runtime_delivery(self, agent: Agent) -> RuntimeDeliveryRead | None:
        if agent.status != AgentStatus.RUNNING:
            raise RuntimeError("Agent is not running")
        delivery = self.delivery_repository.claim_next_inbound(agent_id=agent.id)
        if delivery is not None:
            self.notify_processing_feedback(
                ProcessingFeedbackContext(
                    connection_id=delivery.connection_id,
                    stage=ProcessingFeedbackStage.CLAIMED,
                    location=delivery.envelope.location,
                    provider_message_id=delivery.envelope.provider_message_id,
                )
            )
        return delivery

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
            if not result.succeeded:
                self._notify_runtime_failure_feedback(agent.id, delivery_id)
        return completed

    def _notify_runtime_failure_feedback(self, agent_id: UUID, delivery_id: UUID) -> None:
        """Notify terminal runtime failure without coupling it to completion."""
        try:
            status = self.delivery_repository.delivery_status(
                delivery_id,
                direction=CommunicationDirection.INBOUND,
            )
            if status != CommunicationDeliveryStatus.DEAD_LETTERED:
                return
            delivery = self.delivery_repository.get_inbound_runtime_delivery(delivery_id, agent_id=agent_id)
            if delivery is not None:
                self.notify_processing_feedback(
                    ProcessingFeedbackContext(
                        connection_id=delivery.connection_id,
                        stage=ProcessingFeedbackStage.FAILED,
                        location=delivery.envelope.location,
                        provider_message_id=delivery.envelope.provider_message_id,
                    )
                )
        except Exception as exc:
            logger.warning(
                "Communication terminal-failure feedback context failed for Delivery %s (%s)",
                delivery_id,
                type(exc).__name__,
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

    def accept_driver_event(
        self,
        connection_id: UUID,
        provided_key: str,
        payload: dict[str, Any],
    ) -> list[AcceptedCommunicationRead]:
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled:
            raise PermissionError("Communication Connection not found")
        driver_key = decrypt_token(
            connection.driver_key_encrypted,
            self.config.agent_token_encryption_key,
        )
        if not secrets.compare_digest(driver_key, provided_key):
            raise PermissionError("Invalid Platform Driver credential")
        plugin = self.plugins.require(connection.platform_key)
        settings = plugin.settings_model.model_validate(connection.settings)
        return self._accept_admitted_payload(connection, plugin, settings, payload)

    def accept_plugin_payload(
        self,
        connection_id: UUID,
        payload: dict[str, Any],
    ) -> list[AcceptedCommunicationRead]:
        """Accept an event from a plugin task already bound to its Connection."""
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled:
            return []
        plugin = self.plugins.require(connection.platform_key)
        settings = plugin.settings_model.model_validate(connection.settings)
        return self._accept_admitted_payload(connection, plugin, settings, payload)

    def _accept_admitted_payload(
        self,
        connection: CommunicationConnection,
        plugin: PlatformPlugin,
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
        if envelopes:
            envelopes = self._enrich_inbound(connection, plugin, settings, envelopes)
        accepted: list[AcceptedCommunicationRead] = []
        for envelope in envelopes:
            result = self.accept_inbound(connection.id, envelope)
            accepted.append(result)
            if not result.duplicate and result.status == CommunicationDeliveryStatus.PENDING:
                self._notify_processing_feedback(connection, ProcessingFeedbackStage.ACCEPTED, envelope)
        return accepted

    def _enrich_inbound(
        self,
        connection: CommunicationConnection,
        plugin: PlatformPlugin,
        settings: PlatformSettings,
        envelopes: list[NormalizedCommunicationEnvelope],
    ) -> list[NormalizedCommunicationEnvelope]:
        """Resolve optional provider names before durable persistence.

        Best-effort: any failure (decrypt, validation, or a plugin's own
        provider lookups) falls back to the envelopes as normalized rather
        than delaying or rejecting durable acceptance.
        """
        try:
            credentials = plugin.credentials_model.model_validate(
                json.loads(decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key))
            )
            return plugin.enrich_inbound(settings, credentials, envelopes)
        except Exception as exc:
            # Validation errors can include input values. Credentials are
            # decrypted only for this best-effort lookup and must never appear
            # in logs, even when a stored payload is malformed.
            logger.warning(
                "Communication inbound enrichment failed for Connection %s (%s)",
                connection.id,
                type(exc).__name__,
            )
            return envelopes

    def notify_processing_feedback(self, context: ProcessingFeedbackContext) -> None:
        """Best-effort feedback hook for a provider-owned delivery lifecycle."""
        try:
            connection = self.connection_repository.get_active(context.connection_id)
            if connection is not None:
                self._notify_processing_feedback_context(connection, context)
        except Exception as exc:
            logger.warning(
                "Communication processing feedback lookup failed for Connection %s (%s)",
                context.connection_id,
                type(exc).__name__,
            )

    def _notify_processing_feedback(
        self,
        connection: CommunicationConnection,
        stage: ProcessingFeedbackStage,
        envelope: NormalizedCommunicationEnvelope,
    ) -> None:
        self._notify_processing_feedback_context(
            connection,
            ProcessingFeedbackContext(
                connection_id=connection.id,
                stage=stage,
                location=envelope.location,
                provider_message_id=envelope.provider_message_id,
            ),
        )

    def _notify_processing_feedback_context(
        self,
        connection: CommunicationConnection,
        context: ProcessingFeedbackContext,
    ) -> None:
        try:
            plugin = self.plugins.require(connection.platform_key)
            if PlatformCapability.PROCESSING_FEEDBACK not in plugin.capabilities:
                return
            settings = plugin.settings_model.model_validate(connection.settings)
            credentials = plugin.credentials_model.model_validate(
                json.loads(decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key))
            )
            plugin.processing_feedback(
                settings,
                credentials,
                context,
            )
        except Exception as exc:
            logger.warning(
                "Communication processing feedback %s failed for Connection %s (%s)",
                context.stage.value,
                connection.id,
                type(exc).__name__,
            )

    def _admit_plugin_payload(
        self,
        connection_id: UUID,
        plugin: PlatformPlugin,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        try:
            result = plugin.admit_inbound(
                settings,
                payload,
                context=InboundAdmissionContext(
                    connection_id=connection_id,
                    thread_is_agent_owned=lambda location: self.delivery_repository.thread_has_agent_state(
                        connection_id=connection_id,
                        location=location,
                    ),
                ),
            )
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

    def accept_provider_webhook(
        self,
        connection_id: UUID,
        payload: dict[str, Any],
        authorization: str,
    ) -> list[AcceptedCommunicationRead]:
        connection = self.connection_repository.get_active(connection_id)
        if connection is None or not connection.enabled:
            raise PermissionError("Communication Connection not found")
        plugin = self.plugins.require(connection.platform_key)
        credentials = plugin.credentials_model.model_validate(
            json.loads(decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key))
        )
        plugin.verify_webhook(credentials, payload, authorization)
        return self.accept_plugin_payload(connection.id, payload)
