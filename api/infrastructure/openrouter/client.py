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

# Remaining credit, cached separately from the catalogue: it changes constantly,
# whereas the catalogue barely moves, so they cannot share a TTL.
_credits_cache: tuple[float, float | None] | None = None
_credits_lock = threading.Lock()


class OpenRouterError(Exception):
    pass


def clear_models_cache() -> None:
    """Drops the cached catalogue and credit reading. Intended for tests."""
    global _credits_cache
    with _cache_lock:
        _cache.clear()
        _key_locks.clear()
    with _credits_lock:
        _credits_cache = None


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

    def get_credits_remaining(self) -> float | None:
        """Credit left on the inference key, or None when there is no answer.

        None covers two different situations on purpose, and neither should be shown
        as a number: the key has no credit limit set (OpenRouter reports null), or
        the poll failed. Runway is undefined in both cases, and inventing a figure
        for a page about money is worse than admitting we do not know.

        Reads GET /key rather than the account-wide /credits endpoint, which needs a
        management key that can also mint and delete keys — too much privilege for a
        read. Cached for the same TTL as the credits metric.
        """
        global _credits_cache
        ttl = self.config.openrouter_credits_cache_ttl_seconds
        now = time.monotonic()
        with _credits_lock:
            if _credits_cache is not None and now - _credits_cache[0] < ttl:
                return _credits_cache[1]

        remaining: float | None = None
        if self.config.openrouter_api_key:
            try:
                resp = httpx.get(
                    f"{self.config.openrouter_base_url.rstrip('/')}/key",
                    headers={"Authorization": f"Bearer {self.config.openrouter_api_key}"},
                    timeout=10,
                )
                resp.raise_for_status()
                limit_remaining = resp.json()["data"]["limit_remaining"]
                remaining = None if limit_remaining is None else float(limit_remaining)
            except Exception:
                # Never let a credit poll fail a cost page. The caller renders
                # "unknown" runway and everything else on the page still works.
                logger.warning("Failed to read OpenRouter credit balance", exc_info=True)

        with _credits_lock:
            _credits_cache = (time.monotonic(), remaining)
        return remaining

    def get_generation(self, generation_id: str) -> dict | None:
        """Return the true cost and token counts OpenRouter recorded for one call.

        Used to recover spend that LiteLLM dropped on streamed responses. Reading
        generation metadata does not consume credits — a 260-request benchmark moved
        the account total by $0.00000000.

        Returns None when OpenRouter has no such generation (HTTP 404). The caller
        decides what that means; the cost sync treats it as retryable and leaves the
        row alone, because writing a zero would claim "this call was free" when the
        truth is "we could not find out". Every other failure raises, for the same
        reason.
        """
        url = f"{self.config.openrouter_base_url}/generation"
        headers = {}
        if self.config.openrouter_api_key:
            headers["Authorization"] = f"Bearer {self.config.openrouter_api_key}"
        try:
            resp = httpx.get(url, params={"id": generation_id}, headers=headers, timeout=30)
            if resp.status_code == httpx.codes.NOT_FOUND:
                return None
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenRouterError(f"OpenRouter generation lookup failed with {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"OpenRouter generation lookup failed: {exc}") from exc

        data = resp.json().get("data")
        if not isinstance(data, dict):
            raise OpenRouterError(f"Unexpected /generation response for {generation_id}")
        return data

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
