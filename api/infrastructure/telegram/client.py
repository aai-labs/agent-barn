import hashlib
import json
import logging

from api.core.config import get_config
from api.infrastructure.http import resilient_request
from api.infrastructure.shared.cache import cached as _cached

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org"
_TIMEOUT_SECONDS = 15
_CHAT_CACHE_TTL_SECONDS = 600


def _request_json(url: str, *, label: str = "Telegram") -> dict:
    resp = resilient_request(
        "GET",
        url,
        timeout=_TIMEOUT_SECONDS,
        label=label,
        retry_server_errors=True,
    )
    if resp.status_code == 401:
        return {"ok": False, "description": "Unauthorized — invalid bot token"}
    if resp.status_code == 404:
        return {"ok": False, "description": "Not Found — invalid bot token format"}
    resp.raise_for_status()
    return resp.json()


def validate_bot_token(bot_token: str) -> tuple[bool, str, dict]:
    """Validate a Telegram bot token via the getMe API.

    Returns (ok, error_reason, bot_info). On success bot_info contains
    {"id": int, "is_bot": bool, "username": str, "first_name": str}.
    """
    if get_config().skip_telegram_token_validation:
        return True, "", {"username": "skipped"}

    url = f"{_BASE}/bot{bot_token}/getMe"
    try:
        data = _request_json(url, label="Telegram getMe")
    except Exception:
        return False, "Could not reach Telegram to validate bot token", {}

    if data.get("ok"):
        return True, "", data.get("result", {})

    description = data.get("description", "unknown error")
    return False, f"Telegram bot token is invalid: {description}", {}


def _fetch_chat_display_name(bot_token: str, chat_id: str) -> str | None:
    url = f"{_BASE}/bot{bot_token}/getChat?chat_id={chat_id}"
    try:
        data = _request_json(url, label="Telegram getChat")
    except Exception:
        return None
    if not data.get("ok"):
        return None
    result = data.get("result", {})
    chat_type = result.get("type", "")
    if chat_type in ("group", "supergroup", "channel"):
        return result.get("title")
    return result.get("first_name") or result.get("username") or result.get("last_name")


def get_chat_display_name(bot_token: str, chat_id: str) -> str | None:
    """Resolve a Telegram chat/user ID to a human-readable name (cached).

    The cache key is scoped by a hash of the bot token: Telegram chat/user IDs
    are provider-global, not bot-scoped, so two different bot credentials
    resolving the same ID must never share a cached name.
    """
    token_key = hashlib.sha256(bot_token.encode()).hexdigest()
    return _cached(
        f"tg_chat:{token_key}:{chat_id}",
        lambda: _fetch_chat_display_name(bot_token, chat_id),
        ttl=_CHAT_CACHE_TTL_SECONDS,
    )


def send_message(bot_token: str, chat_id: str, text: str, *, thread_id: str | None = None) -> str:
    payload: dict[str, str | int] = {"chat_id": chat_id, "text": text}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    response = resilient_request(
        "POST",
        f"{_BASE}/bot{bot_token}/sendMessage",
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        timeout=_TIMEOUT_SECONDS,
        label="Telegram sendMessage",
        retry_server_errors=True,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram sendMessage error: {body.get('description', 'unknown error')}")
    message_id = body.get("result", {}).get("message_id")
    if message_id is None:
        raise RuntimeError("Telegram sendMessage returned no message id")
    return str(message_id)
