import json
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    CommunicationDeliveryStatus,
    CommunicationDirection,
    OutboundCommunicationEnvelope,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import ProcessingFeedbackContext
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class OutboundCommunicationProcessor:
    config: Config
    deliveries: CommunicationDeliveryRepository
    connections: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry
    gateway: CommunicationsGatewayService

    def process_one(self) -> bool:
        delivery = self.deliveries.claim_next_outbound()
        if delivery is None:
            return False
        outbound: OutboundCommunicationEnvelope | None = None
        try:
            outbound = OutboundCommunicationEnvelope.model_validate(delivery.envelope)
            connection = self.connections.get_active(delivery.connection_id)
            if connection is None or not connection.enabled:
                raise RuntimeError("Communication Connection is unavailable")
            plugin = self.plugins.require(connection.platform_key)
            settings = plugin.settings_model.model_validate(connection.settings)
            credentials = plugin.credentials_model.model_validate(
                json.loads(
                    decrypt_token(
                        connection.credentials_encrypted,
                        self.config.agent_token_encryption_key,
                    )
                )
            )
            provider_message_id = plugin.send(
                settings,
                credentials,
                outbound,
            )
        except Exception as exc:
            logger.warning("Outbound Communication Delivery %s failed: %s", delivery.id, exc)
            completed = self.deliveries.complete_outbound(
                delivery.id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            if completed and outbound is not None and self._is_dead_lettered(delivery.id):
                self._notify_feedback(delivery.connection_id, outbound, ProcessingFeedbackStage.FAILED)
        else:
            completed = self.deliveries.complete_outbound(
                delivery.id,
                provider_message_id=provider_message_id,
            )
            if completed and outbound is not None and self._is_succeeded(delivery.id):
                self._notify_feedback(delivery.connection_id, outbound, ProcessingFeedbackStage.SUCCEEDED)
        return True

    def _is_dead_lettered(self, delivery_id: UUID) -> bool:
        return self._is_status(delivery_id, CommunicationDeliveryStatus.DEAD_LETTERED)

    def _is_succeeded(self, delivery_id: UUID) -> bool:
        return self._is_status(delivery_id, CommunicationDeliveryStatus.SUCCEEDED)

    def _is_status(self, delivery_id: UUID, expected: CommunicationDeliveryStatus) -> bool:
        try:
            return (
                self.deliveries.delivery_status(
                    delivery_id,
                    direction=CommunicationDirection.OUTBOUND,
                )
                == expected
            )
        except Exception as exc:
            detail = " ".join(str(exc).split())[:160]
            logger.warning(
                "Communication feedback status lookup failed for Delivery %s (%s): %s",
                delivery_id,
                type(exc).__name__,
                detail,
            )
            return False

    def _notify_feedback(
        self,
        connection_id: UUID,
        outbound: OutboundCommunicationEnvelope,
        stage: ProcessingFeedbackStage,
    ) -> None:
        self.gateway.notify_processing_feedback(
            ProcessingFeedbackContext(
                connection_id=connection_id,
                stage=stage,
                location=outbound.location,
                provider_message_id=outbound.reply_to_provider_message_id,
                source_delivery_id=outbound.source_delivery_id,
            )
        )
