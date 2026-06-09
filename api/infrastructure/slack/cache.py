import logging
import threading
import time
from collections.abc import Callable

from api.core.config import get_config
from api.infrastructure.slack.errors import SlackFetchError

logger = logging.getLogger(__name__)

# Process-local TTL cache for the workspace directory (users/channels), keyed by
# entity kind + hashed bot token. Slack has no user-search endpoint and users.list
# is rate-limited, so we sweep every page once per TTL and filter in memory.
# Fragmented per pod; swap for a shared store (Redis) keyed the same way if needed.
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def clear_directory_cache() -> None:
    """Drops all cached directory entries. Intended for tests."""
    with _cache_lock:
        _cache.clear()
        _key_locks.clear()


def _key_lock(key: str) -> threading.Lock:
    with _cache_lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def cached(key: str, fetch: Callable[[], list[dict]]) -> list[dict]:
    """Returns cached entries for key, refreshing via fetch on miss/expiry.
    Per-key locking ensures a miss triggers exactly one Slack sweep.

    A failed fetch is never cached: stale entries are served if present (so one
    transient error doesn't blank the directory for a whole TTL), otherwise the
    SlackFetchError propagates so callers can surface it instead of returning an
    empty list that looks like a genuinely empty workspace.
    """
    ttl = get_config().slack_directory_cache_ttl_seconds
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    with _key_lock(key):
        # Re-check: another thread may have refreshed while we waited.
        now = time.monotonic()
        with _cache_lock:
            entry = _cache.get(key)
            if entry and now - entry[0] < ttl:
                return entry[1]
        try:
            data = fetch()
        except SlackFetchError as exc:
            with _cache_lock:
                stale = _cache.get(key)
            if stale is not None:
                logger.warning(
                    "Slack directory refresh failed (%s); serving stale entries", exc
                )
                return stale[1]
            logger.warning(
                "Slack directory refresh failed (%s); no cached entries to serve", exc
            )
            raise
        with _cache_lock:
            _cache[key] = (time.monotonic(), data)
        return data
