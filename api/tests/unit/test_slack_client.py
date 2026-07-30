from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.infrastructure.slack.client import (
    SlackClient,
    SlackFetchError,
    clear_directory_cache,
)

_REQUEST = httpx.Request("GET", "https://slack.com/api/users.list")


def _resp(page: dict, *, status: int = 200, headers: dict | None = None) -> httpx.Response:
    """An httpx.Response carrying page as the JSON body."""
    return httpx.Response(status, json=page, headers=headers, request=_REQUEST)


def _mock_httpx(items: list) -> MagicMock:
    """Mock for httpx.request: each item is a Response to return or an Exception to raise."""
    return MagicMock(side_effect=list(items))


_USERS_PAGE = {
    "ok": True,
    "members": [{"id": "U1", "name": "alice", "profile": {}}],
    "response_metadata": {"next_cursor": ""},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_directory_cache()
    yield
    clear_directory_cache()


# --- pagination & parsing --------------------------------------------------


def test_list_users_paginates_all_pages():
    pages = [
        {
            "ok": True,
            "members": [{"id": "U1", "name": "alice", "profile": {"display_name": "Al"}}],
            "response_metadata": {"next_cursor": "next"},
        },
        {
            "ok": True,
            "members": [{"id": "U2", "name": "bob", "profile": {"display_name": "Bobby"}}],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    with patch("httpx.request", _mock_httpx([_resp(p) for p in pages])):
        users = SlackClient("xoxb-token").list_users()

    assert [u["id"] for u in users] == ["U1", "U2"]


def test_list_users_extracts_display_name_and_excludes_bots_and_deleted():
    pages = [
        {
            "ok": True,
            "members": [
                {
                    "id": "U1",
                    "name": "alice",
                    "real_name": "Alice Top",
                    "profile": {"display_name": "Ally", "real_name": "Alice Smith"},
                },
                {"id": "U2", "name": "bob", "deleted": True},
                {"id": "U3", "name": "mybot", "is_bot": True},
            ],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    with patch("httpx.request", _mock_httpx([_resp(p) for p in pages])):
        users = SlackClient("xoxb-token").list_users()

    assert len(users) == 1
    assert users[0] == {
        "id": "U1",
        "name": "alice",
        "real_name": "Alice Smith",
        "display_name": "Ally",
    }


def test_list_users_search_matches_display_name():
    pages = [
        {
            "ok": True,
            "members": [
                {"id": "U1", "name": "alice", "profile": {"display_name": "Wizard"}},
                {"id": "U2", "name": "bob", "profile": {"display_name": "Sorcerer"}},
            ],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    with patch("httpx.request", _mock_httpx([_resp(p) for p in pages])):
        users = SlackClient("xoxb-token").list_users(search="wiz")

    assert [u["id"] for u in users] == ["U1"]


def test_list_channels_paginates_all_pages():
    pages = [
        {
            "ok": True,
            "channels": [{"id": "C1", "name": "general", "is_private": False}],
            "response_metadata": {"next_cursor": "next"},
        },
        {
            "ok": True,
            "channels": [{"id": "C2", "name": "secret", "is_private": True}],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    with patch("httpx.request", _mock_httpx([_resp(p) for p in pages])):
        channels = SlackClient("xoxb-token").list_channels()

    assert [c["id"] for c in channels] == ["C1", "C2"]
    assert channels[1]["is_private"] is True


_MIXED_USERS_PAGE = {
    "ok": True,
    "members": [
        {"id": "U1", "name": "alice", "profile": {"display_name": "Ally"}},
        {"id": "U2", "name": "bob", "deleted": True},
        {"id": "U3", "name": "mybot", "is_bot": True},
    ],
    "response_metadata": {"next_cursor": ""},
}


def test_list_users_include_flags_keep_bots_and_deleted():
    with patch("httpx.request", _mock_httpx([_resp(_MIXED_USERS_PAGE)])):
        users = SlackClient("xoxb-token").list_users(include_bots=True, include_deleted=True)

    assert [u["id"] for u in users] == ["U1", "U2", "U3"]
    # The projection never leaks the internal filter flags.
    assert set(users[0]) == {"id", "name", "real_name", "display_name"}


def test_list_users_can_include_only_bots_or_only_deleted():
    with patch("httpx.request", _mock_httpx([_resp(_MIXED_USERS_PAGE)])):
        c = SlackClient("xoxb-token")
        with_bots = c.list_users(include_bots=True)  # one sweep, then cached
        with_deleted = c.list_users(include_deleted=True)

    assert [u["id"] for u in with_bots] == ["U1", "U3"]
    assert [u["id"] for u in with_deleted] == ["U1", "U2"]


# --- error semantics -------------------------------------------------------


def test_fetcher_non_ok_response_raises_and_is_not_cached():
    bad = {"ok": False, "error": "ratelimited"}
    mock = _mock_httpx([_resp(bad), _resp(_USERS_PAGE)])
    with patch("httpx.request", mock):
        c = SlackClient("xoxb-token")
        with pytest.raises(SlackFetchError):
            c.list_users()
        # The failure was not cached: the next call sweeps Slack again.
        users = c.list_users()

    assert [u["id"] for u in users] == ["U1"]
    assert mock.call_count == 2


# --- token validation ------------------------------------------------------


def test_validate_bot_token_ok():
    with patch("httpx.request", _mock_httpx([_resp({"ok": True})])):
        ok, message = SlackClient("xoxb-token").validate_bot_token()

    assert ok is True
    assert message == ""


def test_validate_bot_token_maps_known_error():
    with patch("httpx.request", _mock_httpx([_resp({"ok": False, "error": "invalid_auth"})])):
        ok, message = SlackClient("xoxb-token").validate_bot_token()

    assert ok is False
    assert "invalid" in message.lower()


def test_validate_bot_token_falls_back_for_unknown_error():
    with patch("httpx.request", _mock_httpx([_resp({"ok": False, "error": "weird"})])):
        ok, message = SlackClient("xoxb-token").validate_bot_token()

    assert ok is False
    assert "weird" in message


def test_validate_app_token_ok_uses_app_token():
    mock = _mock_httpx([_resp({"ok": True})])
    with patch("httpx.request", mock):
        ok, message = SlackClient("xoxb-token", app_token="xapp-token").validate_app_token()

    assert ok is True
    assert message == ""
    # The app token (not the bot token) authenticates the app-level call.
    assert mock.call_args.kwargs["headers"]["Authorization"] == "Bearer xapp-token"


def test_validate_app_token_missing_returns_error_without_request():
    mock = _mock_httpx([])  # must not be called
    with patch("httpx.request", mock):
        ok, message = SlackClient("xoxb-token").validate_app_token()

    assert ok is False
    assert message
    assert mock.call_count == 0


def test_validate_bot_token_unreachable_slack_returns_error():
    # A transport error is retried to the budget, then surfaces as a clean message.
    errors = [httpx.ConnectError("down", request=_REQUEST)] * 3
    with patch("httpx.request", _mock_httpx(errors)):
        with patch("api.infrastructure.slack.transport.time.sleep"):
            ok, message = SlackClient("xoxb-token").validate_bot_token()

    assert ok is False
    assert "Could not reach Slack" in message


# --- get_bot_info ----------------------------------------------------------


def test_get_bot_info_returns_fields_on_success():
    payload = {
        "ok": True,
        "app_id": "ATEST123",
        "user": "my-bot",
        "team": "My Workspace",
    }
    with patch("httpx.request", _mock_httpx([_resp(payload)])):
        info = SlackClient("xoxb-token").get_bot_info()

    assert info == {"app_id": "ATEST123", "bot_name": "my-bot", "team": "My Workspace"}


def test_get_bot_info_returns_empty_dict_on_non_ok():
    with patch("httpx.request", _mock_httpx([_resp({"ok": False, "error": "invalid_auth"})])):
        info = SlackClient("xoxb-token").get_bot_info()

    assert info == {}


def test_get_bot_info_returns_empty_dict_on_network_error():
    errors = [httpx.ConnectError("down", request=_REQUEST)] * 3
    with patch("httpx.request", _mock_httpx(errors)):
        with patch("api.infrastructure.slack.transport.time.sleep"):
            info = SlackClient("xoxb-token").get_bot_info()

    assert info == {}
