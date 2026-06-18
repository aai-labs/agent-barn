from unittest.mock import MagicMock, patch

import pytest

from api.infrastructure.slack import cache
from api.infrastructure.slack.cache import cached, clear_directory_cache
from api.infrastructure.slack.errors import SlackFetchError


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_directory_cache()
    yield
    clear_directory_cache()


def _ttl(seconds: int) -> MagicMock:
    cfg = MagicMock()
    cfg.slack_directory_cache_ttl_seconds = seconds
    return cfg


def test_fetch_result_is_cached():
    fetch = MagicMock(return_value=[{"id": "U1"}])
    first = cached("users:abc", fetch)
    second = cached("users:abc", fetch)

    assert first == second == [{"id": "U1"}]
    assert fetch.call_count == 1  # second call served from cache


def test_separate_keys_fetch_independently():
    users = MagicMock(return_value=[{"id": "U1"}])
    channels = MagicMock(return_value=[{"id": "C1"}])

    assert cached("users:abc", users) == [{"id": "U1"}]
    assert cached("channels:abc", channels) == [{"id": "C1"}]
    assert users.call_count == 1
    assert channels.call_count == 1


def test_refetches_after_ttl_expiry():
    fetch = MagicMock(side_effect=[[{"id": "U1"}], [{"id": "U2"}]])
    with patch.object(cache, "get_config", return_value=_ttl(0)):
        first = cached("users:abc", fetch)
        second = cached("users:abc", fetch)

    assert first == [{"id": "U1"}]
    assert second == [{"id": "U2"}]
    assert fetch.call_count == 2


def test_failed_fetch_is_not_cached():
    fetch = MagicMock(side_effect=[SlackFetchError("boom"), [{"id": "U1"}]])
    with pytest.raises(SlackFetchError):
        cached("users:abc", fetch)
    # The failure was not cached: the next call sweeps again.
    assert cached("users:abc", fetch) == [{"id": "U1"}]
    assert fetch.call_count == 2


def test_refresh_failure_serves_stale_cache():
    # TTL 0 forces a refresh on every call; the refresh fails, so the previously
    # cached entries must still be served rather than blanked out.
    fetch = MagicMock(side_effect=[[{"id": "U1"}], SlackFetchError("boom")])
    with patch.object(cache, "get_config", return_value=_ttl(0)):
        first = cached("users:abc", fetch)
        second = cached("users:abc", fetch)

    assert first == [{"id": "U1"}]
    assert second == [{"id": "U1"}]  # stale entries served
    assert fetch.call_count == 2
