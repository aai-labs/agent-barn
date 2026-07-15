import logging
import time

import httpx

from api.core.config import get_config

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org"
_MAX_RETRIES = 2
_DEFAULT_RETRY_AFTER_SECONDS = 1
_RATE_LIMIT_MAX_WAIT_SECONDS = 30
_TIMEOUT_SECONDS = 15


def _retry_after_seconds(raw: str | None) -> int:
    if raw is None:
        return _DEFAULT_RETRY_AFTER_SECONDS
    try:
        seconds = int(raw)
    except ValueError:
        seconds = _DEFAULT_RETRY_AFTER_SECONDS
    return max(1, min(seconds, _RATE_LIMIT_MAX_WAIT_SECONDS))


def _request_json(url: str) -> dict:
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        except httpx.TransportError as exc:
            if attempt == _MAX_RETRIES:
                raise
            logger.warning(
                "Telegram transport error on %s (%s); retrying in %ss (attempt %d/%d)",
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
                "Telegram rate-limited; retrying in %ss (attempt %d/%d)",
                wait,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        if resp.status_code == 401:
            return {"ok": False, "description": "Unauthorized — invalid bot token"}
        if resp.status_code == 404:
            return {"ok": False, "description": "Not Found — invalid bot token format"}
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"exhausted retries for {url}")


def validate_bot_token(bot_token: str) -> tuple[bool, str, dict]:
    """Validate a Telegram bot token via the getMe API.

    Returns (ok, error_reason, bot_info). On success bot_info contains
    {"id": int, "is_bot": bool, "username": str, "first_name": str}.
    """
    if get_config().skip_telegram_token_validation:
        return True, "", {"username": "skipped"}

    url = f"{_BASE}/bot{bot_token}/getMe"
    try:
        data = _request_json(url)
    except Exception as exc:
        return False, f"Could not reach Telegram to validate bot token: {exc}", {}

    if data.get("ok"):
        return True, "", data.get("result", {})

    description = data.get("description", "unknown error")
    return False, f"Telegram bot token is invalid: {description}", {}


def get_chat_display_name(bot_token: str, chat_id: str) -> str | None:
    """Resolve a Telegram chat/user ID to a human-readable name.

    Returns a display name or None if the lookup fails.
    """
    url = f"{_BASE}/bot{bot_token}/getChat?chat_id={chat_id}"
    try:
        data = _request_json(url)
    except Exception:
        return None
    if not data.get("ok"):
        return None
    result = data.get("result", {})
    chat_type = result.get("type", "")
    if chat_type in ("group", "supergroup", "channel"):
        return result.get("title")
    return result.get("first_name") or result.get("username") or result.get("last_name")
