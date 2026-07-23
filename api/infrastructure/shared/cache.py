import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def clear_cache() -> None:
    """Drop all cached entries. Intended for tests."""
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


def cached(key: str, fetch: Callable[[], T], *, ttl: float) -> T:
    """Return cached value for *key*, refreshing via *fetch* on miss/expiry.

    Per-key locking ensures a miss triggers exactly one fetch. A failed fetch
    is never cached: stale entries are served if present, otherwise the
    exception propagates.
    """
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    with _key_lock(key):
        now = time.monotonic()
        with _cache_lock:
            entry = _cache.get(key)
            if entry and now - entry[0] < ttl:
                return entry[1]
        try:
            data = fetch()
        except Exception as exc:
            with _cache_lock:
                stale = _cache.get(key)
            if stale is not None:
                logger.warning("Cache refresh failed for %s (%s); serving stale entry", key, exc)
                return stale[1]
            raise
        with _cache_lock:
            _cache[key] = (time.monotonic(), data)
        return data
