import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.posthog.exceptions import RetryablePostHogException, TerminalPostHogException

logger = logging.getLogger(__name__)

_BATCH_PATH = "/batch/"
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
_RETRYABLE_STATUSES = frozenset({408, 429})
_ERROR_BODY_LOG_LIMIT = 500


@singleton
@inject
@dataclass
class PostHogClient:
    config: Config

    def send_batch(self, messages: list[dict[str, Any]]) -> None:
        url = f"{self.config.analytics_posthog_host.rstrip('/')}{_BATCH_PATH}"
        body = {
            "api_key": self.config.analytics_posthog_project_token,
            "batch": messages,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        try:
            response = httpx.post(url, json=body, timeout=_TIMEOUT)
        except httpx.TransportError as exc:
            logger.warning("PostHog batch failed: url=%s error=%s", url, type(exc).__name__)
            raise RetryablePostHogException(f"PostHog unreachable: {type(exc).__name__}") from exc

        status = response.status_code
        if status == 200:
            return
        detail = f"HTTP {status}: {response.text[:_ERROR_BODY_LOG_LIMIT]}"
        logger.warning("PostHog batch rejected: url=%s %s", url, detail)
        if status in _RETRYABLE_STATUSES or status >= 500:
            raise RetryablePostHogException(f"PostHog rejected the batch ({detail})")
        raise TerminalPostHogException(f"PostHog rejected the batch ({detail})")
