from unittest.mock import patch

import httpx

from api.infrastructure.telegram.client import get_chat_display_name

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
