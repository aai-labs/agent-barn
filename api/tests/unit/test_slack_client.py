import json
from unittest.mock import MagicMock, patch

import pytest

from api.infrastructure.slack import client as slack_client
from api.infrastructure.slack.client import SlackClient, clear_directory_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_directory_cache()
    yield
    clear_directory_cache()


def _mock_urlopen(pages: list[dict]) -> MagicMock:
    """Builds a urlopen mock that returns each page in order as a context manager."""
    mock = MagicMock()

    def _make(page: dict):
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(page).encode()
        return cm

    mock.side_effect = [_make(p) for p in pages]
    return mock


def test_list_users_paginates_all_pages():
    pages = [
        {
            "ok": True,
            "members": [
                {"id": "U1", "name": "alice", "profile": {"display_name": "Al"}}
            ],
            "response_metadata": {"next_cursor": "next"},
        },
        {
            "ok": True,
            "members": [
                {"id": "U2", "name": "bob", "profile": {"display_name": "Bobby"}}
            ],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    with patch("urllib.request.urlopen", _mock_urlopen(pages)):
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
    with patch("urllib.request.urlopen", _mock_urlopen(pages)):
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
    with patch("urllib.request.urlopen", _mock_urlopen(pages)):
        users = SlackClient("xoxb-token").list_users(search="wiz")

    assert [u["id"] for u in users] == ["U1"]


def test_list_users_is_cached_per_token():
    pages = [
        {
            "ok": True,
            "members": [{"id": "U1", "name": "alice", "profile": {}}],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    mock = _mock_urlopen(pages)
    with patch("urllib.request.urlopen", mock):
        c = SlackClient("xoxb-token")
        first = c.list_users()
        second = c.list_users()

    assert first == second
    assert mock.call_count == 1  # second call served from cache


def test_list_users_refetches_after_ttl_expiry():
    pages = [
        {
            "ok": True,
            "members": [{"id": "U1", "name": "alice", "profile": {}}],
            "response_metadata": {"next_cursor": ""},
        },
        {
            "ok": True,
            "members": [{"id": "U2", "name": "bob", "profile": {}}],
            "response_metadata": {"next_cursor": ""},
        },
    ]
    mock = _mock_urlopen(pages)
    cfg = MagicMock()
    cfg.slack_directory_cache_ttl_seconds = 0
    with patch.object(slack_client, "get_config", return_value=cfg):
        with patch("urllib.request.urlopen", mock):
            c = SlackClient("xoxb-token")
            first = c.list_users()
            second = c.list_users()

    assert [u["id"] for u in first] == ["U1"]
    assert [u["id"] for u in second] == ["U2"]
    assert mock.call_count == 2


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
    with patch("urllib.request.urlopen", _mock_urlopen(pages)):
        channels = SlackClient("xoxb-token").list_channels()

    assert [c["id"] for c in channels] == ["C1", "C2"]
    assert channels[1]["is_private"] is True
