import time  # noqa: F401 — kept so tests can patch transport.time

from api.core.config import get_config
from api.infrastructure.http import (
    DEFAULT_RETRY_AFTER_SECONDS as _DEFAULT_RETRY_AFTER_SECONDS,
)
from api.infrastructure.http import (
    MAX_RETRIES as _MAX_RETRIES,
)
from api.infrastructure.http import (
    RATE_LIMIT_MAX_WAIT_SECONDS as _RATE_LIMIT_MAX_WAIT_SECONDS,
)
from api.infrastructure.http import (
    resilient_request,
)
from api.infrastructure.http import (
    retry_after_seconds as _retry_after_seconds,
)
from api.infrastructure.public_http import pin_to_public_address

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
    public_only: bool = False,
) -> dict:
    """Perform a Slack API request with retry logic, returning parsed JSON.

    ``public_only`` is for a user-supplied Slack-compatible server: the request is
    pinned to the host's checked public addresses, and raises ``NonPublicDestination``
    for a private, internal or non-https one. Redirects are never followed.
    """
    timeout = get_config().slack_request_timeout_seconds
    extensions = None
    if public_only:
        pinned = pin_to_public_address(url)
        url, headers, extensions = pinned.url, {**headers, **pinned.headers}, pinned.extensions
    resp = resilient_request(
        method,
        url,
        headers=headers,
        params=params,
        content=content,
        timeout=timeout,
        label="Slack",
        extensions=extensions,
    )
    resp.raise_for_status()
    return resp.json()
