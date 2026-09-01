import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationSender,
    ConnectionObservedStatus,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
)
from api.domains.communications.plugins.web import WebPlatformPlugin
from api.domains.communications.repository import (
    CommunicationConnectionConflictError,
    CommunicationConnectionRepository,
)
from api.domains.rbac.catalog import PermissionKey
from api.domains.web_chat.models import MAIN_THREAD_ID, WebChatMessageRead, WebChatThreadRead
from api.domains.web_chat.repository import WebChatRepository
from api.infrastructure.crypto import encrypt_token

WEB_CONNECTION_DISPLAY_NAME = "Web Chat"
POLL_INTERVAL_SECONDS = 0.5
HEARTBEAT_EVERY_TICKS = 30


@inject
@singleton
@dataclass
class WebChatService:
    config: Config
    authorization: AgentAuthorization
    connections: CommunicationConnectionRepository
    web_chat_repository: WebChatRepository
    gateway: CommunicationsGatewayService

    def send_message(self, agent_id: UUID, text: str, thread_id: str, context: CurrentUserContext) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        envelope = NormalizedCommunicationEnvelope(
            provider_message_id=secrets.token_urlsafe(16),
            occurred_at=datetime.now(UTC),
            location=self._location(context, thread_id),
            sender=CommunicationSender(
                id=str(context.user.id),
                display_name=context.user.full_name or context.user.email,
            ),
            text=text,
        )
        self.gateway.accept_inbound(connection.id, envelope)

    def list_messages(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        thread_id: str,
        after_id: UUID | None = None,
    ) -> list[WebChatMessageRead]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        location = self._location(context, thread_id)
        messages = self.web_chat_repository.list_thread_messages(
            connection_id=connection.id,
            channel_id=location.id,
            thread_id=thread_id,
            after_id=after_id,
        )
        return [WebChatMessageRead.model_validate(m) for m in messages]

    def list_threads(self, agent_id: UUID, context: CurrentUserContext) -> list[WebChatThreadRead]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        summaries = self.web_chat_repository.list_threads(
            connection_id=connection.id,
            channel_id=str(context.user.id),
        )
        return [
            WebChatThreadRead(
                thread_id=summary.thread_id,
                last_occurred_at=summary.last_occurred_at,
                last_content=summary.last_content,
            )
            for summary in summaries
        ]

    def stream_updates(self, agent_id: UUID, context: CurrentUserContext, thread_id: str) -> Iterator[str]:
        """Poll for new messages and yield them as Server-Sent Event frames.

        Outbound Agent replies land in agent_chat_message the moment the
        Runtime posts them (see WebPlatformPlugin), so polling this table is
        enough to deliver near-real-time updates without any cross-process
        pub/sub — the outbound processor that "delivers" other platforms runs
        in a separate worker process from this API, so an in-memory queue
        would not see those writes.
        """
        last_id: UUID | None = None
        for message in self.list_messages(agent_id, context, thread_id, after_id=None):
            last_id = message.id
            yield f"data: {message.model_dump_json()}\n\n"

        ticks = 0
        while True:
            time.sleep(POLL_INTERVAL_SECONDS)
            new_messages = self.list_messages(agent_id, context, thread_id, after_id=last_id)
            for message in new_messages:
                last_id = message.id
                yield f"data: {message.model_dump_json()}\n\n"
            ticks += 1
            if not new_messages and ticks % HEARTBEAT_EVERY_TICKS == 0:
                yield ": keep-alive\n\n"

    def _location(self, context: CurrentUserContext, thread_id: str) -> ConversationLocation:
        channel_id = str(context.user.id)
        return ConversationLocation(id=channel_id, type="DM", thread_id=thread_id or MAIN_THREAD_ID)

    def _get_or_create_connection(self, agent_id: UUID, organization_id: UUID) -> CommunicationConnection:
        existing = self.connections.get_active_by_platform_key(agent_id, WebPlatformPlugin.key)
        if existing is not None:
            return existing
        connection = CommunicationConnection(
            organization_id=organization_id,
            agent_id=agent_id,
            platform_key=WebPlatformPlugin.key,
            display_name=WEB_CONNECTION_DISPLAY_NAME,
            enabled=True,
            schema_version=1,
            settings={},
            credentials_encrypted=encrypt_token("{}", self.config.agent_token_encryption_key),
            driver_key_encrypted=encrypt_token(
                secrets.token_urlsafe(32),
                self.config.agent_token_encryption_key,
            ),
            observed_status=ConnectionObservedStatus.CONNECTED,
        )
        try:
            return self.connections.create(connection)
        except CommunicationConnectionConflictError:
            # Lost a create race against another request for the same Agent's
            # first message; the winner's row is what we want.
            existing = self.connections.get_active_by_platform_key(agent_id, WebPlatformPlugin.key)
            if existing is None:
                raise
            return existing
