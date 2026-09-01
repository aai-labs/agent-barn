import secrets
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
    CommunicationDeliveryStatus,
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
from api.domains.conversations.models import MessageDirection
from api.domains.rbac.catalog import PermissionKey
from api.domains.web_chat.models import MAIN_THREAD_ID, WebChatMessageRead, WebChatThreadRead
from api.domains.web_chat.repository import WebChatRepository
from api.infrastructure.communication_signals import CommunicationSignalBus
from api.infrastructure.crypto import encrypt_token

WEB_CONNECTION_DISPLAY_NAME = "Web Chat"
TITLE_PREVIEW_LENGTH = 48


@inject
@singleton
@dataclass
class WebChatService:
    config: Config
    authorization: AgentAuthorization
    connections: CommunicationConnectionRepository
    web_chat_repository: WebChatRepository
    gateway: CommunicationsGatewayService
    signals: CommunicationSignalBus

    def send_message(
        self,
        agent_id: UUID,
        text: str,
        thread_id: str,
        context: CurrentUserContext,
    ) -> WebChatMessageRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        location = self._location(context, thread_id)
        self.web_chat_repository.restore_thread_if_deleted(
            connection_id=connection.id,
            channel_id=location.id,
            thread_id=location.thread_id or MAIN_THREAD_ID,
        )
        envelope = NormalizedCommunicationEnvelope(
            provider_message_id=secrets.token_urlsafe(16),
            occurred_at=datetime.now(UTC),
            location=location,
            sender=CommunicationSender(
                id=str(context.user.id),
                display_name=context.user.full_name or context.user.email,
            ),
            text=text,
        )
        accepted = self.gateway.accept_inbound(connection.id, envelope)
        return WebChatMessageRead(
            id=accepted.message_id,
            direction=MessageDirection.INBOUND,
            content=envelope.text,
            occurred_at=envelope.occurred_at,
            delivery_status=accepted.status,
        )

    def stop_generation(
        self,
        agent_id: UUID,
        thread_id: str,
        context: CurrentUserContext,
    ) -> bool:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        location = self._location(context, thread_id)
        delivery_id = self.gateway.find_active_inbound_delivery(connection.id, location)
        if delivery_id is None:
            return False
        return self.gateway.request_cancel_delivery(agent.id, delivery_id)

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
        statuses = self.web_chat_repository.delivery_statuses_for_messages([message.id for message in messages])
        return [
            WebChatMessageRead(
                id=message.id,
                direction=message.direction,
                content=message.content,
                occurred_at=message.occurred_at,
                delivery_status=statuses.get(message.id, CommunicationDeliveryStatus.SUCCEEDED),
            )
            for message in messages
        ]

    def list_threads(self, agent_id: UUID, context: CurrentUserContext) -> list[WebChatThreadRead]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        channel_id = str(context.user.id)
        summaries = self.web_chat_repository.list_threads(connection_id=connection.id, channel_id=channel_id)
        metadata = self.web_chat_repository.list_thread_metadata(connection_id=connection.id, channel_id=channel_id)
        threads = []
        for summary in summaries:
            meta = metadata.get(summary.thread_id)
            threads.append(
                WebChatThreadRead(
                    thread_id=summary.thread_id,
                    title=self._title_for(
                        summary.thread_id,
                        meta.display_name if meta else None,
                        summary.first_content,
                    ),
                    last_occurred_at=summary.last_occurred_at,
                    last_content=summary.last_content,
                )
            )
        return threads

    def rename_thread(
        self,
        agent_id: UUID,
        thread_id: str,
        display_name: str,
        context: CurrentUserContext,
    ) -> WebChatThreadRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        channel_id = str(context.user.id)
        self.web_chat_repository.rename_thread(
            connection_id=connection.id,
            channel_id=channel_id,
            thread_id=thread_id,
            display_name=display_name.strip(),
        )
        threads = self.list_threads(agent_id, context)
        for thread in threads:
            if thread.thread_id == thread_id:
                return thread
        # No messages yet — nothing for list_threads to surface a preview
        # from, but the rename itself is already durable.
        return WebChatThreadRead(
            thread_id=thread_id,
            title=display_name.strip(),
            last_occurred_at=None,
            last_content=None,
        )

    def delete_thread(self, agent_id: UUID, thread_id: str, context: CurrentUserContext) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        self.web_chat_repository.soft_delete_thread(
            connection_id=connection.id,
            channel_id=str(context.user.id),
            thread_id=thread_id,
        )

    def stream_updates(self, agent_id: UUID, context: CurrentUserContext, thread_id: str) -> Iterator[str]:
        """Replay durable thread state, then wake only on committed signals."""
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        cursor = self.signals.latest_cursor(agent.id)
        emitted: dict[UUID, WebChatMessageRead] = {}

        for message in self.list_messages(agent_id, context, thread_id, after_id=None):
            emitted[message.id] = message
            yield f"data: {message.model_dump_json()}\n\n"

        while True:
            cursor, notifications = self.signals.wait(agent.id, cursor)
            if not notifications:
                yield ": keep-alive\n\n"
                continue
            for message in self.list_messages(agent_id, context, thread_id, after_id=None):
                if emitted.get(message.id) == message:
                    continue
                emitted[message.id] = message
                yield f"data: {message.model_dump_json()}\n\n"

    @staticmethod
    def _title_for(thread_id: str, display_name: str | None, first_content: str | None) -> str:
        if display_name:
            return display_name
        if first_content:
            collapsed = " ".join(first_content.split())
            if len(collapsed) > TITLE_PREVIEW_LENGTH:
                return collapsed[:TITLE_PREVIEW_LENGTH].rstrip() + "…"
            return collapsed
        if thread_id == MAIN_THREAD_ID:
            return "Main chat"
        return f"Chat {thread_id[:8]}"

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
