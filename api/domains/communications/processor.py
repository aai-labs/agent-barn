import json
import logging
from dataclasses import dataclass

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import (
    OutboundCommunicationEnvelope,
)
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.communications.transport import require_gateway_transport
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class OutboundCommunicationProcessor:
    config: Config
    deliveries: CommunicationDeliveryRepository
    connections: CommunicationConnectionRepository
    agents: AgentRepository
    plugins: PlatformPluginRegistry

    def process_one(self) -> bool:
        delivery = self.deliveries.claim_next_outbound()
        if delivery is None:
            return False
        outbound: OutboundCommunicationEnvelope | None = None
        try:
            outbound = OutboundCommunicationEnvelope.model_validate(delivery.envelope)
            if outbound.origin != "reply":
                raise PermissionError("Gateway-initiated delivery is retired")
            connection = self.connections.get_active(delivery.connection_id)
            if connection is None or not connection.enabled:
                raise RuntimeError("Communication Connection is unavailable")
            require_gateway_transport(connection.platform_key)
            plugin = self.plugins.require_delivery(connection.platform_key)
            settings = plugin.settings_model.model_validate(connection.settings)
            credentials = plugin.credentials_model.model_validate(
                json.loads(
                    decrypt_token(
                        connection.credentials_encrypted,
                        self.config.agent_token_encryption_key,
                    )
                )
            )
            agent = self.agents.get_by_id(connection.agent_id)
            if agent is None:
                raise RuntimeError("Agent is unavailable")
            provider_message_id = plugin.send(
                settings,
                credentials,
                self._with_agent_identity(outbound, agent.name),
                idempotency_key=delivery.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Outbound Communication Delivery %s failed (%s)", delivery.id, type(exc).__name__)
            normalized_error = normalize_communication_error(exc, operation="send_message")
            self.deliveries.complete_outbound(
                delivery.id,
                error_code=normalized_error.code,
                error_message=normalized_error.summary,
                error_details=normalized_error.details,
            )
        else:
            self.deliveries.complete_outbound(
                delivery.id,
                provider_message_id=provider_message_id,
            )
        return True

    @staticmethod
    def _with_agent_identity(
        outbound: OutboundCommunicationEnvelope,
        agent_name: str,
    ) -> OutboundCommunicationEnvelope:
        """Add the Agent's name to the outbound envelope's provider metadata.

        Platforms that address a reply as the Agent itself (currently only email,
        whose `From` display name is the Agent) need an identity the stored
        envelope does not carry. Resolved here per delivery rather than stored on
        the Connection, so renaming an Agent shows on its next reply.
        """
        return outbound.model_copy(
            update={"provider_metadata": {**outbound.provider_metadata, "agent_name": agent_name}}
        )
