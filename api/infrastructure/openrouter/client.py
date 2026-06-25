import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from injector import inject, singleton

from api.core.config import Config, get_config

logger = logging.getLogger(__name__)

# Process-local TTL cache for the OpenRouter model catalogue. The catalogue is
# global to the account (not per-agent) and changes rarely, so we sweep it once
# per TTL and serve everyone from memory. Fragmented per pod; swap for a shared
# store (Redis) keyed the same way if needed.
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


class OpenRouterError(Exception):
    pass


def clear_models_cache() -> None:
    """Drops the cached catalogue. Intended for tests."""
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


def _cached(key: str, fetch: Callable[[], list[dict]]) -> list[dict]:
    """Returns the cached catalogue for key, refreshing via fetch on miss/expiry.
    Per-key locking ensures a miss triggers exactly one OpenRouter fetch.
    """
    ttl = get_config().openrouter_models_cache_ttl_seconds
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
        data = fetch()
        with _cache_lock:
            _cache[key] = (time.monotonic(), data)
        return data


@inject
@dataclass
@singleton
class OpenRouterClient:
    config: Config

    def list_models(self) -> list[dict]:
        """Returns the OpenRouter catalogue as {id, name, context_length, pricing}."""
        return _cached(self.config.openrouter_base_url, self._fetch_models)

    def _fetch_models(self) -> list[dict]:
        url = f"{self.config.openrouter_base_url}/models"
        headers = {}
        if self.config.openrouter_api_key:
            headers["Authorization"] = f"Bearer {self.config.openrouter_api_key}"
        try:
            resp = httpx.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"Failed to fetch OpenRouter models: {exc}") from exc
        models: list[dict] = []
        for entry in resp.json().get("data", []):
            model_id = entry.get("id")
            if not model_id:
                continue
            models.append(
                {
                    "id": model_id,
                    "name": entry.get("name") or model_id,
                    "context_length": entry.get("context_length"),
                    "pricing": entry.get("pricing"),
                }
            )
        return models
