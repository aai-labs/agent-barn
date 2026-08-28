import json
from unittest.mock import MagicMock, patch

import httpx

from api.infrastructure.telegram.client import get_chat_display_name, send_message

_REQUEST = httpx.Request("GET", "https://api.telegram.org/bot123:ABC/getChat")


def _resp(body: dict, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, request=_REQUEST)


def test_get_chat_display_name_user():
    resp = _resp({"ok": True, "result": {"type": "private", "first_name": "Alice"}})
    with patch("httpx.request", return_value=resp):
        assert get_chat_display_name("123:ABC", "42") == "Alice"


def test_get_chat_display_name_user_username_fallback():
    resp = _resp({"ok": True, "result": {"type": "private", "username": "bob"}})
    with patch("httpx.request", return_value=resp):
        assert get_chat_display_name("123:ABC", "42") == "bob"


def test_get_chat_display_name_group():
    resp = _resp({"ok": True, "result": {"type": "supergroup", "title": "Dev Chat"}})
    with patch("httpx.request", return_value=resp):
        assert get_chat_display_name("123:ABC", "-100123") == "Dev Chat"


def test_get_chat_display_name_channel():
    resp = _resp({"ok": True, "result": {"type": "channel", "title": "Announcements"}})
    with patch("httpx.request", return_value=resp):
        assert get_chat_display_name("123:ABC", "-100456") == "Announcements"


def test_get_chat_display_name_not_found():
    resp = _resp({"ok": False, "description": "chat not found"}, status=400)
    with patch("httpx.request", return_value=resp):
        assert get_chat_display_name("123:ABC", "999") is None


def test_get_chat_display_name_network_error():
    with patch(
        "httpx.request",
        side_effect=httpx.ConnectError("timeout"),
    ):
        assert get_chat_display_name("123:ABC", "42") is None


def test_get_chat_display_name_cache_does_not_cross_contaminate_different_bot_tokens():
    """Telegram chat/user IDs are provider-global, not bot-scoped: two
    different bot credentials resolving the same chat_id must not share a
    cached name across unrelated Connections.
    """
    response_one = _resp({"ok": True, "result": {"type": "private", "first_name": "Bot One's Alice"}})
    response_two = _resp({"ok": True, "result": {"type": "private", "first_name": "Bot Two's Alice"}})
    with patch("httpx.request", side_effect=[response_one, response_two]):
        first = get_chat_display_name("111:AAA", "42")
        second = get_chat_display_name("222:BBB", "42")

    assert first == "Bot One's Alice"
    assert second == "Bot Two's Alice"


@patch("api.infrastructure.telegram.client.resilient_request")
def test_send_message_carries_the_provider_idempotency_key(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"ok": True, "result": {"message_id": 17}}
    mock_request.return_value = response

    message_id = send_message("bot-value", "chat-1", "reply", idempotency_key="provider-key")

    assert message_id == "17"
    assert mock_request.call_args.kwargs["headers"]["Idempotency-Key"] == "provider-key"
    assert json.loads(mock_request.call_args.kwargs["content"])["text"] == "reply"
