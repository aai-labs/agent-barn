import logging
import time

import httpx

from api.core.config import get_config
from api.infrastructure.slack.errors import SlackFetchError

logger = logging.getLogger(__name__)

# A request is retried a bounded number of times so transient Slack failures
# don't surface as a hard error (or poison the directory cache): HTTP 429 (rate
# limit, honoring Retry-After) and transport errors (connection dropped mid-body,
# resets, timeouts) — httpx.TransportError covers all of these.
_MAX_RETRIES = 2
_RATE_LIMIT_MAX_WAIT_SECONDS = 30
_DEFAULT_RETRY_AFTER_SECONDS = 1


def _retry_after_seconds(raw: str | None) -> int:
    """Seconds to wait per a 429 response's Retry-After header, clamped to a sane range."""
    if raw is None:
        return _DEFAULT_RETRY_AFTER_SECONDS
    try:
        seconds = int(raw)
    except ValueError:
        seconds = _DEFAULT_RETRY_AFTER_SECONDS
    return max(1, min(seconds, _RATE_LIMIT_MAX_WAIT_SECONDS))


def request_json(
    method: str,
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    content: bytes | None = None,
) -> dict:
    """Performs the request via httpx and parses the JSON body, retrying transient failures.

    Retries up to _MAX_RETRIES times on HTTP 429 (honoring Retry-After) and on
    transport errors (connection dropped mid-body, resets, timeouts). Slack signals
    application errors as HTTP 200 with {"ok": false}, so those flow to the caller;
    other non-2xx statuses raise. A retryable error past the budget propagates.
    """
    timeout = get_config().slack_request_timeout_seconds
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                content=content,
                timeout=timeout,
            )
        except httpx.TransportError as exc:
            if attempt == _MAX_RETRIES:
                raise
            logger.warning(
                "Slack transport error on %s (%s); retrying in %ss (attempt %d/%d)",
                url,
                exc,
                _DEFAULT_RETRY_AFTER_SECONDS,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(_DEFAULT_RETRY_AFTER_SECONDS)
            continue
        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            wait = _retry_after_seconds(resp.headers.get("Retry-After"))
            logger.warning(
                "Slack rate-limited on %s; retrying in %ss (attempt %d/%d)",
                url,
                wait,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    # Unreachable: the loop either returns or raises on the final attempt.
    raise SlackFetchError(f"exhausted retries for {url}")
