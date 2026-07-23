import time  # noqa: F401 — kept so tests can patch transport.time

from api.core.config import get_config
from api.infrastructure.http import (
    DEFAULT_RETRY_AFTER_SECONDS as _DEFAULT_RETRY_AFTER_SECONDS,
    MAX_RETRIES as _MAX_RETRIES,
    RATE_LIMIT_MAX_WAIT_SECONDS as _RATE_LIMIT_MAX_WAIT_SECONDS,
    resilient_request,
    retry_after_seconds as _retry_after_seconds,
)

__all__ = [
    "_DEFAULT_RETRY_AFTER_SECONDS",
    "_MAX_RETRIES",
    "_RATE_LIMIT_MAX_WAIT_SECONDS",
    "_retry_after_seconds",
    "request_json",
]


def request_json(
    method: str,
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    content: bytes | None = None,
) -> dict:
    """Perform a Slack API request with retry logic, returning parsed JSON."""
    timeout = get_config().slack_request_timeout_seconds
    resp = resilient_request(
        method,
        url,
        headers=headers,
        params=params,
        content=content,
        timeout=timeout,
        label="Slack",
    )
    resp.raise_for_status()
    return resp.json()
