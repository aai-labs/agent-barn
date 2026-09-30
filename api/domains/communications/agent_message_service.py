"""One provider-neutral acceptance path for scheduled and interactive messages."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.agent_message_repository import AgentMessageConflictError, AgentMessageRepository
from api.domains.communications.execution_context import read_execution_token
from api.domains.communications.models import (
    AgentMessageCreate,
    AgentMessageRead,
    CommunicationConnection,
    OriginMessageDestination,
    OutboundCommunicationEnvelope,
    OutboundTargetRequest,
    PlatformCapability,
)
from api.domains.communications.plugins.base import AgentInitiatedDeliverySettings
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.conversations.models import ConversationType
from api.infrastructure.crypto import decrypt_token


@inject
@singleton
@dataclass
class AgentMessageService:
    config: Config
    repository: AgentMessageRepository
    connections: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry

    def _default_connection(self, agent: Agent) -> CommunicationConnection:
        connection = self.connections.runtime_default(agent.id, agent.organization_id)
        if connection is None:
            raise AgentMessageConflictError("Agent has no configured default delivery target")
        return connection

    def _explicit_connection(self, agent: Agent, source_id: UUID, attempt: int) -> CommunicationConnection:
        """Send on the Connection the conversation is already happening on.

        An Agent may hold several Connections per platform, so scanning for a capable
        one would have to guess between workspaces -- and guessing wrong leaks a message
        into the wrong company's Slack. The originating inbound execution names exactly
        one Connection, so there is nothing to disambiguate.
        """
        connection_id = self.repository.execution_connection_id(agent.id, source_id, attempt)
        connection = self.connections.runtime_connection(agent.id, agent.organization_id, connection_id)
        if connection is None:
            raise AgentMessageConflictError("Communication Connection is unavailable")
        return connection

    def _origin_connection(self, agent: Agent, destination: OriginMessageDestination) -> CommunicationConnection:
        """Verify the Connection a scheduled job claims to come from still belongs to this Agent."""
        connection = self.connections.runtime_connection(agent.id, agent.organization_id, destination.connection_id)
        if connection is None:
            raise AgentMessageConflictError("The Connection this scheduled job was created from is unavailable")
        return connection

    def _origin_target(
        self, agent: Agent, connection: CommunicationConnection, destination: OriginMessageDestination
    ) -> OutboundTargetRequest:
        """Turn a verified origin into an ordinary target request, refusing unknown conversations."""
        conversation = self.repository.origin_conversation_type(agent.id, connection.id, destination.channel_id)
        if conversation is None:
            raise AgentMessageConflictError("The conversation this scheduled job was created from is unknown")
        return OutboundTargetRequest(
            kind="dm" if conversation == ConversationType.DM else "channel",
            recipient=destination.channel_id,
            thread_id=destination.thread_id,
        )

    def _require_available(self, connection: CommunicationConnection) -> None:
        if not connection.enabled:
            raise AgentMessageConflictError("Communication Connection is unavailable")
        plugin = self.plugins.require(connection.platform_key)
        if PlatformCapability.AGENT_INITIATED_DELIVERY not in plugin.capabilities:
            raise AgentMessageConflictError("Platform does not support agent-initiated delivery")

    def submit_agent_message(self, agent: Agent, request: AgentMessageCreate) -> AgentMessageRead:
        try:
            return self._submit(agent, request)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except AgentMessageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, "Invalid or ambiguous outbound destination") from exc

    def _submit(self, agent: Agent, request: AgentMessageCreate) -> AgentMessageRead:
        source_id = None
        attempt = None
        if request.context.kind == "interactive":
            source_id, attempt = read_execution_token(
                self.config.agent_token_encryption_key,
                agent.id,
                request.context.execution_token,
            )
            execution_id = str(source_id)
        else:
            execution_id = request.context.run_id
        digest = hashlib.sha256(
            json.dumps(
                {
                    "text": request.text,
                    "destination": request.destination.model_dump(mode="json"),
                    "execution": execution_id,
                    "context": request.context.kind,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        key = hashlib.sha256(request.idempotency_key.encode()).hexdigest()
        # A lost acknowledgement must work after the default changes or the source finishes.
        existing = self.repository.existing(agent.id, key, digest)
        if existing is not None:
            return existing
        if agent.status != AgentStatus.RUNNING:
            raise AgentMessageConflictError("Agent is not running")
        if request.destination.kind == "default":
            connection = self._default_connection(agent)
        elif request.destination.kind == "origin":
            connection = self._origin_connection(agent, request.destination)
        else:
            # Explicit implies interactive: validate_context rejects scheduled + explicit.
            assert source_id is not None
            connection = self._explicit_connection(agent, source_id, attempt or 0)
        self._require_available(connection)
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
        if request.destination.kind == "default":
            if not isinstance(settings, AgentInitiatedDeliverySettings) or settings.default_delivery_target is None:
                raise AgentMessageConflictError("Agent has no configured default delivery target")
            target_request = settings.default_delivery_target
        elif request.destination.kind == "origin":
            target_request = self._origin_target(agent, connection, request.destination)
        else:
            target_request = request.destination.target
        target = plugin.resolve_outbound_target(settings, credentials, target_request)
        envelope = OutboundCommunicationEnvelope(
            origin="cron" if request.context.kind == "scheduled" else "user_directed",
            execution_id=execution_id,
            source_delivery_id=source_id,
            text=request.text,
            location=target.location,
            provider_metadata=target.provider_metadata,
        )
        return self.repository.accept(
            agent=agent, connection=connection, key=key, digest=digest, envelope=envelope, attempt=attempt
        )
