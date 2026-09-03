import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.models import CommunicationDeliveryStatus
from api.domains.conversations.models import MessageDirection
from api.domains.rbac.catalog import PermissionKey
from api.domains.web_chat.models import WebChatMessageRead
from api.domains.web_chat.service import WebChatService
from api.infrastructure.communication_signals import (
    CommunicationSignal,
    CommunicationSignalBus,
    CommunicationSignalType,
)


def test_stream_updates_authorizes_before_returning_async_stream() -> None:
    agent_id = uuid4()
    context = cast(CurrentUserContext, SimpleNamespace(user=SimpleNamespace(id=uuid4())))
    authorization = Mock()
    authorization.require_action.return_value = SimpleNamespace(id=agent_id, organization_id=uuid4())
    connections = Mock()
    connections.get_active_by_platform_key.return_value = SimpleNamespace(id=uuid4())
    signals = Mock()
    signals.latest_cursor_async = AsyncMock(return_value="10-0")
    signals.wait_async = AsyncMock(return_value=("10-0", []))
    service = WebChatService(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key")),
        authorization=authorization,
        connections=connections,
        web_chat_repository=Mock(),
        gateway=Mock(),
        signals=cast(CommunicationSignalBus, signals),
    )

    stream = service.stream_updates(agent_id, context, "thread-1")

    authorization.require_action.assert_called_once_with(context, agent_id, PermissionKey.ACTIVITY_READ)
    with patch.object(service, "_list_messages_for_connection", return_value=[]):

        async def read_heartbeat() -> str:
            return await stream.__anext__()

        assert asyncio.run(read_heartbeat()) == ": keep-alive\n\n"

    signals.latest_cursor_async.assert_awaited_once_with(agent_id)
    signals.wait_async.assert_awaited_once_with(agent_id, "10-0")


def test_stream_updates_uses_incremental_reads_and_targeted_status_refreshes() -> None:
    agent_id = uuid4()
    connection_id = uuid4()
    user_id = uuid4()
    changed_delivery_id = uuid4()
    context = cast(CurrentUserContext, SimpleNamespace(user=SimpleNamespace(id=user_id)))
    authorization = Mock()
    authorization.require_action.return_value = SimpleNamespace(id=agent_id, organization_id=uuid4())
    connections = Mock()
    connections.get_active_by_platform_key.return_value = SimpleNamespace(id=connection_id)
    signals = Mock()
    signals.latest_cursor_async = AsyncMock(return_value="10-0")
    signals.wait_async = AsyncMock(
        side_effect=[
            (
                "11-0",
                [
                    CommunicationSignal(type=CommunicationSignalType.DELIVERY_AVAILABLE),
                    CommunicationSignal(
                        type=CommunicationSignalType.MESSAGE_CHANGED,
                        delivery_id=changed_delivery_id,
                    ),
                ],
            ),
            (
                "12-0",
                [CommunicationSignal(type=CommunicationSignalType.DELIVERY_AVAILABLE)],
            ),
        ]
    )
    occurred_at = datetime.now(UTC)
    first_new_message = WebChatMessageRead(
        id=uuid4(),
        direction=MessageDirection.INBOUND,
        content="new message",
        occurred_at=occurred_at,
        delivery_status=CommunicationDeliveryStatus.PENDING,
    )
    existing_message = WebChatMessageRead(
        id=uuid4(),
        direction=MessageDirection.INBOUND,
        content="existing message",
        occurred_at=occurred_at,
        delivery_status=CommunicationDeliveryStatus.PROCESSING,
    )
    changed_message = existing_message.model_copy(update={"delivery_status": CommunicationDeliveryStatus.SUCCEEDED})
    second_new_message = WebChatMessageRead(
        id=uuid4(),
        direction=MessageDirection.OUTBOUND,
        content="reply",
        occurred_at=occurred_at,
        delivery_status=CommunicationDeliveryStatus.SUCCEEDED,
    )
    service = WebChatService(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key")),
        authorization=authorization,
        connections=connections,
        web_chat_repository=Mock(),
        gateway=Mock(),
        signals=cast(CommunicationSignalBus, signals),
    )

    with (
        patch.object(
            service,
            "_list_messages_for_connection",
            side_effect=[[], [first_new_message], [second_new_message]],
        ) as list_messages,
        patch.object(service, "_message_for_delivery", return_value=changed_message) as message_for_delivery,
    ):
        stream = service.stream_updates(agent_id, context, "thread-1")

        async def read_frames() -> tuple[str, str, str]:
            return await stream.__anext__(), await stream.__anext__(), await stream.__anext__()

        frames = asyncio.run(read_frames())

    assert frames == (
        f"data: {first_new_message.model_dump_json()}\n\n",
        f"data: {changed_message.model_dump_json()}\n\n",
        f"data: {second_new_message.model_dump_json()}\n\n",
    )
    assert [call.kwargs["after_id"] for call in list_messages.call_args_list] == [
        None,
        None,
        first_new_message.id,
    ]
    message_for_delivery.assert_called_once_with(
        delivery_id=changed_delivery_id,
        connection_id=connection_id,
        channel_id=str(user_id),
        thread_id="thread-1",
    )
