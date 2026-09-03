import asyncio
import secrets
from collections.abc import AsyncIterator
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
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.rbac.catalog import PermissionKey
from api.domains.web_chat.models import MAIN_THREAD_ID, WebChatMessageRead, WebChatThreadRead
from api.domains.web_chat.repository import WebChatDeliveryState, WebChatRepository
from api.infrastructure.communication_signals import (
    CommunicationSignalBus,
    CommunicationSignalType,
)
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
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
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
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
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
        connection = self._get_existing_connection(agent.id)
        if connection is None:
            return []
        location = self._location(context, thread_id)
        return self._list_messages_for_connection(
            connection_id=connection.id,
            channel_id=location.id,
            thread_id=location.thread_id or MAIN_THREAD_ID,
            after_id=after_id,
        )

    def _list_messages_for_connection(
        self,
        *,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
        after_id: UUID | None,
    ) -> list[WebChatMessageRead]:
        messages = self.web_chat_repository.list_thread_messages(
            connection_id=connection_id,
            channel_id=channel_id,
            thread_id=thread_id,
            after_id=after_id,
        )
        delivery_states = self.web_chat_repository.delivery_statuses_for_messages([message.id for message in messages])
        return [self._message_read(message, delivery_states.get(message.id)) for message in messages]

    def list_threads(self, agent_id: UUID, context: CurrentUserContext) -> list[WebChatThreadRead]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_existing_connection(agent.id)
        if connection is None:
            return []
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
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
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
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        connection = self._get_or_create_connection(agent.id, agent.organization_id)
        self.web_chat_repository.soft_delete_thread(
            connection_id=connection.id,
            channel_id=str(context.user.id),
            thread_id=thread_id,
        )

    def stream_updates(self, agent_id: UUID, context: CurrentUserContext, thread_id: str) -> AsyncIterator[str]:
        """Authorize eagerly, then replay and asynchronously await committed signals."""
        agent = self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        connection = self._get_existing_connection(agent.id)
        location = self._location(context, thread_id)
        return self._stream_updates(
            agent_id=agent.id,
            connection_id=connection.id if connection is not None else None,
            channel_id=location.id,
            thread_id=location.thread_id or MAIN_THREAD_ID,
        )

    async def _stream_updates(
        self,
        *,
        agent_id: UUID,
        connection_id: UUID | None,
        channel_id: str,
        thread_id: str,
    ) -> AsyncIterator[str]:
        cursor = await self.signals.latest_cursor_async(agent_id)
        # A stream is a GET path too: opening it must not create the built-in
        # Connection. Re-check after taking the cursor so a first send racing
        # stream setup is still included in the initial replay.
        if connection_id is None:
            connection = await asyncio.to_thread(self._get_existing_connection, agent_id)
            connection_id = connection.id if connection is not None else None
        messages = (
            await asyncio.to_thread(
                self._list_messages_for_connection,
                connection_id=connection_id,
                channel_id=channel_id,
                thread_id=thread_id,
                after_id=None,
            )
            if connection_id is not None
            else []
        )
        last_message_id = messages[-1].id if messages else None
        for message in messages:
            yield f"data: {message.model_dump_json()}\n\n"

        while True:
            cursor, notifications = await self.signals.wait_async(agent_id, cursor)
            if not notifications:
                yield ": keep-alive\n\n"
                continue

            if connection_id is None:
                connection = await asyncio.to_thread(self._get_existing_connection, agent_id)
                connection_id = connection.id if connection is not None else None
                if connection_id is None:
                    continue

            refreshed_ids: set[UUID] = set()
            messages = await asyncio.to_thread(
                self._list_messages_for_connection,
                connection_id=connection_id,
                channel_id=channel_id,
                thread_id=thread_id,
                after_id=last_message_id,
            )
            for message in messages:
                last_message_id = message.id
                refreshed_ids.add(message.id)
                yield f"data: {message.model_dump_json()}\n\n"

            for signal in notifications:
                if (
                    signal.type
                    not in {
                        CommunicationSignalType.DELIVERY_CANCELLED,
                        CommunicationSignalType.MESSAGE_CHANGED,
                    }
                    or signal.delivery_id is None
                ):
                    continue
                message = await asyncio.to_thread(
                    self._message_for_delivery,
                    delivery_id=signal.delivery_id,
                    connection_id=connection_id,
                    channel_id=channel_id,
                    thread_id=thread_id,
                )
                if message is None or message.id in refreshed_ids:
                    continue
                yield f"data: {message.model_dump_json()}\n\n"

    def _message_for_delivery(
        self,
        *,
        delivery_id: UUID,
        connection_id: UUID,
        channel_id: str,
        thread_id: str,
    ) -> WebChatMessageRead | None:
        result = self.web_chat_repository.get_message_for_delivery(
            delivery_id=delivery_id,
            connection_id=connection_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )
        if result is None:
            return None
        message, delivery_state = result
        return self._message_read(message, delivery_state)

    @staticmethod
    def _message_read(
        message: AgentChatMessage,
        delivery_state: WebChatDeliveryState | None,
    ) -> WebChatMessageRead:
        return WebChatMessageRead(
            id=message.id,
            direction=message.direction,
            content=message.content,
            occurred_at=message.occurred_at,
            delivery_status=(
                delivery_state.status if delivery_state is not None else CommunicationDeliveryStatus.SUCCEEDED
            ),
            cancel_requested_at=delivery_state.cancel_requested_at if delivery_state is not None else None,
        )

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

    def _get_existing_connection(self, agent_id: UUID) -> CommunicationConnection | None:
        return self.connections.get_active_by_platform_key(agent_id, WebPlatformPlugin.key)

    def _get_or_create_connection(self, agent_id: UUID, organization_id: UUID) -> CommunicationConnection:
        existing = self._get_existing_connection(agent_id)
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
            existing = self._get_existing_connection(agent_id)
            if existing is None:
                raise
            return existing
