import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    NormalizedCommunicationEnvelope,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
    RuntimeReplyCreate,
)
from api.domains.communications.plugins.base import InboundAdmissionContext
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import decrypt_token


@inject
@singleton
@dataclass
class CommunicationsGatewayService:
    config: Config
    agent_repository: AgentRepository
    delivery_repository: CommunicationDeliveryRepository
    connection_repository: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry

    def accept_inbound(
        self,
        connection_id: UUID,
        envelope: NormalizedCommunicationEnvelope,
    ) -> AcceptedCommunicationRead:
        return self.delivery_repository.accept_inbound(
            connection_id=connection_id,
            envelope=envelope,
        )

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

    def claim_runtime_delivery(self, agent: Agent) -> RuntimeDeliveryRead | None:
        if agent.status != AgentStatus.RUNNING:
            raise RuntimeError("Agent is not running")
        return self.delivery_repository.claim_next_inbound(agent_id=agent.id)

    def complete_runtime_delivery(
        self,
        agent: Agent,
        delivery_id: UUID,
        result: RuntimeDeliveryResult,
    ) -> bool:
        return self.delivery_repository.complete_runtime_delivery(
            delivery_id,
            agent_id=agent.id,
            succeeded=result.succeeded,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def enqueue_runtime_reply(
        self,
        agent: Agent,
        source_delivery_id: UUID,
        reply: RuntimeReplyCreate,
    ) -> UUID:
        return self.delivery_repository.enqueue_runtime_reply(
            agent_id=agent.id,
            source_delivery_id=source_delivery_id,
            reply=reply,
        )

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
        return [
            self.accept_inbound(connection.id, envelope)
            for envelope in self._admit_plugin_payload(connection.id, plugin, settings, payload)
        ]

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
        return [
            self.accept_inbound(connection.id, envelope)
            for envelope in self._admit_plugin_payload(connection.id, plugin, settings, payload)
        ]

    def _admit_plugin_payload(
        self,
        connection_id: UUID,
        plugin,
        settings,
        payload: dict[str, Any],
    ) -> list[NormalizedCommunicationEnvelope]:
        return plugin.admit_inbound(
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
