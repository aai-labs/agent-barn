import json
from unittest.mock import MagicMock, patch

import httpx
from hamcrest import assert_that, equal_to

from api.infrastructure.telegram.client import _chunk_text, get_chat_display_name, send_message

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

    assert_that(message_id, equal_to("17"))
    assert_that(mock_request.call_args.kwargs["headers"]["Idempotency-Key"], equal_to("provider-key"))
    assert_that(json.loads(mock_request.call_args.kwargs["content"])["text"], equal_to("reply"))


def test_chunk_text_leaves_short_text_untouched():
    assert_that(_chunk_text("hello", limit=10), equal_to(["hello"]))


def test_chunk_text_splits_long_text_on_the_nearest_newline():
    text = ("a" * 10) + "\n" + ("b" * 10)
    chunks = _chunk_text(text, limit=15)
    assert_that(chunks, equal_to([("a" * 10) + "\n", "b" * 10]))


def test_chunk_text_preserves_deliberate_blank_lines_at_split_boundaries():
    text = ("a" * 10) + "\n\n" + ("b" * 10)

    chunks = _chunk_text(text, limit=11)

    assert_that(chunks, equal_to([("a" * 10) + "\n", "\n" + ("b" * 10)]))
    assert_that("".join(chunks), equal_to(text))


def test_chunk_text_uses_telegram_utf16_code_unit_limit():
    text = ("a" * 4095) + "😀"

    chunks = _chunk_text(text)

    assert_that(chunks, equal_to(["a" * 4095, "😀"]))


def test_chunk_text_hard_splits_when_no_newline_is_available():
    text = "a" * 25
    chunks = _chunk_text(text, limit=10)
    assert_that(chunks, equal_to(["a" * 10, "a" * 10, "a" * 5]))


@patch("api.infrastructure.telegram.client.resilient_request")
def test_send_message_over_the_telegram_limit_is_split_across_multiple_calls(mock_request):
    """Telegram rejects sendMessage outright with HTTP 400 past 4096
    characters rather than truncating it — a long agent reply must be split
    into multiple messages instead of dead-lettering the whole delivery."""
    responses = [
        MagicMock(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 17}}),
        MagicMock(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 18}}),
    ]
    mock_request.side_effect = responses

    long_text = "a" * 5000
    message_id = send_message("bot-value", "chat-1", long_text, idempotency_key="provider-key")

    assert_that(message_id, equal_to("18"))
    assert_that(mock_request.call_count, equal_to(2))
    first_call, second_call = mock_request.call_args_list
    assert_that(first_call.kwargs["headers"]["Idempotency-Key"], equal_to("provider-key:0"))
    assert_that(second_call.kwargs["headers"]["Idempotency-Key"], equal_to("provider-key:1"))
    first_text = json.loads(first_call.kwargs["content"])["text"]
    second_text = json.loads(second_call.kwargs["content"])["text"]
    assert_that(len(first_text) <= 4096, equal_to(True))
    assert_that(first_text + second_text, equal_to(long_text))
