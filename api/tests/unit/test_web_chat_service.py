import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.web_chat.service import WebChatService
from api.infrastructure.communication_signals import CommunicationSignalBus


def test_stream_updates_authorizes_before_returning_async_stream() -> None:
    agent_id = uuid4()
    context = cast(CurrentUserContext, SimpleNamespace())
    authorization = Mock()
    authorization.require_action.return_value = SimpleNamespace(id=agent_id, organization_id=uuid4())
    signals = Mock()
    signals.latest_cursor_async = AsyncMock(return_value="10-0")
    signals.wait_async = AsyncMock(return_value=("10-0", []))
    service = WebChatService(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key")),
        authorization=authorization,
        connections=Mock(),
        web_chat_repository=Mock(),
        gateway=Mock(),
        signals=cast(CommunicationSignalBus, signals),
    )

    stream = service.stream_updates(agent_id, context, "thread-1")

    authorization.require_action.assert_called_once_with(context, agent_id, PermissionKey.ACTIVITY_READ)
    with patch.object(service, "list_messages", return_value=[]):

        async def read_heartbeat() -> str:
            return await stream.__anext__()

        assert asyncio.run(read_heartbeat()) == ": keep-alive\n\n"

    signals.latest_cursor_async.assert_awaited_once_with(agent_id)
    signals.wait_async.assert_awaited_once_with(agent_id, "10-0")
