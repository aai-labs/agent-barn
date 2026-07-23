import logging
import time

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RATE_LIMIT_MAX_WAIT_SECONDS = 30
DEFAULT_RETRY_AFTER_SECONDS = 1


def retry_after_seconds(raw: str | None) -> int:
    """Seconds to wait per a 429 response's Retry-After header, clamped to a sane range."""
    if raw is None:
        return DEFAULT_RETRY_AFTER_SECONDS
    try:
        seconds = int(raw)
    except ValueError:
        seconds = DEFAULT_RETRY_AFTER_SECONDS
    return max(1, min(seconds, RATE_LIMIT_MAX_WAIT_SECONDS))


def resilient_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    content: bytes | None = None,
    timeout: float = 15,
    max_retries: int = MAX_RETRIES,
    label: str = "HTTP",
    retry_server_errors: bool = False,
) -> httpx.Response:
    """Perform an HTTP request with retry logic for transient failures.

    Retries on transport errors, 429 (honoring Retry-After), and optionally
    5xx server errors. Returns the httpx.Response for the caller to interpret.
    """
    for attempt in range(max_retries + 1):
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
            if attempt == max_retries:
                raise
            logger.warning(
                "%s transport error (%s); retrying in %ss (attempt %d/%d)",
                label,
                exc,
                DEFAULT_RETRY_AFTER_SECONDS,
                attempt + 1,
                max_retries,
            )
            time.sleep(DEFAULT_RETRY_AFTER_SECONDS)
            continue
        if resp.status_code == 429 and attempt < max_retries:
            wait = retry_after_seconds(resp.headers.get("Retry-After"))
            logger.warning(
                "%s rate-limited; retrying in %ss (attempt %d/%d)",
                label,
                wait,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait)
            continue
        if retry_server_errors and resp.status_code >= 500 and attempt < max_retries:
            logger.warning(
                "%s server error %d; retrying in %ss (attempt %d/%d)",
                label,
                resp.status_code,
                DEFAULT_RETRY_AFTER_SECONDS,
                attempt + 1,
                max_retries,
            )
            time.sleep(DEFAULT_RETRY_AFTER_SECONDS)
            continue
        return resp
    raise RuntimeError(f"exhausted retries for {label}")
