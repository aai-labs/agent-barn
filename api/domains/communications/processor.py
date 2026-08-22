import json
import logging
from dataclasses import dataclass

from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import OutboundCommunicationEnvelope
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

    def process_one(self) -> bool:
        delivery = self.deliveries.claim_next_outbound()
        if delivery is None:
            return False
        try:
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
                OutboundCommunicationEnvelope.model_validate(delivery.envelope),
            )
        except Exception as exc:
            logger.warning("Outbound Communication Delivery %s failed: %s", delivery.id, exc)
            self.deliveries.complete_outbound(
                delivery.id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
        else:
            self.deliveries.complete_outbound(
                delivery.id,
                provider_message_id=provider_message_id,
            )
        return True
