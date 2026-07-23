"""Prometheus metrics for the API and ingest processes.

The two uvicorn processes (main :8000, ingest :8001) each expose their own
/metrics; prometheus_client registries are per-process, so a metric is only
meaningful on the endpoint of the process that writes it.

Registry layout:
- default REGISTRY: process/platform collectors and TOOL_CALLS. Exposed by
  both apps; the counter is only ever incremented in the ingest process.
- PROBE_REGISTRY: gauges refreshed on scrape of the main app only. Kept out
  of the default registry so the ingest endpoint never exports stale zeros
  (e.g. agentfarm_database_up 0) that would trip alerts.
- per-app registries: HTTP metrics from the instrumentator, created fresh in
  setup_http_metrics() so repeated app construction (tests) never collides
  on duplicated timeseries.
"""

import logging
import threading
import time
from collections.abc import Callable

import httpx
from fastapi import FastAPI
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select

from api.core.config import get_config

logger = logging.getLogger(__name__)

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

PROBE_REGISTRY = CollectorRegistry()

TOOL_CALLS = Counter(
    "agentfarm_tool_calls",
    "Completed tool calls by tool name and outcome",
    ["tool_name", "status"],
)

DATABASE_UP = Gauge(
    "agentfarm_database_up",
    "1 if the API can run a query against Postgres, 0 otherwise",
    registry=PROBE_REGISTRY,
)

AGENTS_IN_ERROR = Gauge(
    "agentfarm_agents_in_error",
    "Number of agents whose stored status is ERROR",
    registry=PROBE_REGISTRY,
)

OPENROUTER_CREDITS = Gauge(
    "agentfarm_openrouter_credits_remaining",
    "Credits remaining on the OpenRouter API key's credit limit "
    "(limit_remaining, USD); +Inf when the key has no limit set",
    registry=PROBE_REGISTRY,
)

OPENROUTER_SCRAPE_OK = Gauge(
    "agentfarm_openrouter_credits_scrape_ok",
    "1 if the last OpenRouter credits poll succeeded, 0 otherwise",
    registry=PROBE_REGISTRY,
)

_openrouter_lock = threading.Lock()
_openrouter_polled_at: float | None = None


def clear_openrouter_credits_cache() -> None:
    global _openrouter_polled_at
    with _openrouter_lock:
        _openrouter_polled_at = None


def setup_http_metrics(app: FastAPI) -> CollectorRegistry:
    """Instrument HTTP request metrics into a fresh registry for this app."""
    registry = CollectorRegistry()
    Instrumentator(
        excluded_handlers=["/metrics"],
        registry=registry,
    ).instrument(app)
    return registry


def render_metrics(*registries: CollectorRegistry) -> bytes:
    return b"".join(generate_latest(registry) for registry in registries)


def refresh_database_gauge(engine) -> None:
    try:
        with Session(engine) as session:
            session.exec(select(1))
        DATABASE_UP.set(1)
    except Exception:
        DATABASE_UP.set(0)


def refresh_agents_in_error(count_agents_in_error: Callable[[], int]) -> None:
    try:
        AGENTS_IN_ERROR.set(count_agents_in_error())
    except Exception:
        logger.warning("Failed to refresh agents-in-error gauge", exc_info=True)


def refresh_openrouter_credits() -> None:
    """Poll the key's remaining credit limit, TTL-cached across scrapes.

    Uses GET /key with the ordinary inference key (the account-wide /credits
    endpoint needs a management key, which can also mint/delete keys — too
    much privilege for a metrics probe). limit_remaining is null for a key
    without a credit limit; that maps to +Inf so CreditsLow can never fire
    until an operator sets a limit on the key. On a missing key or failed
    poll, scrape_ok drops to 0 and the credits gauge keeps its last value so
    alerts can distinguish "stale" from "low".
    """
    global _openrouter_polled_at
    config = get_config()

    if not config.openrouter_api_key:
        OPENROUTER_SCRAPE_OK.set(0)
        return

    with _openrouter_lock:
        now = time.monotonic()
        if (
            _openrouter_polled_at is not None
            and now - _openrouter_polled_at < config.openrouter_credits_cache_ttl_seconds
        ):
            return
        _openrouter_polled_at = now

    try:
        response = httpx.get(
            f"{config.openrouter_base_url.rstrip('/')}/key",
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        limit_remaining = response.json()["data"]["limit_remaining"]
        OPENROUTER_CREDITS.set(float("inf") if limit_remaining is None else float(limit_remaining))
        OPENROUTER_SCRAPE_OK.set(1)
    except Exception:
        logger.warning("Failed to poll OpenRouter credits", exc_info=True)
        OPENROUTER_SCRAPE_OK.set(0)
