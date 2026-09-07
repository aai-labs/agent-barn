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
# Telegram's hard sendMessage text limit, measured in UTF-16 code units.
# Longer text is rejected outright with HTTP 400 ("message is too long")
# rather than truncated by the API.
_MAX_MESSAGE_LENGTH = 4096


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _prefix_within_utf16_limit(text: str, limit: int) -> int:
    """Return the largest prefix whose UTF-16 length does not exceed limit."""
    units = 0
    for index, character in enumerate(text):
        character_units = 2 if ord(character) > 0xFFFF else 1
        if units + character_units > limit:
            return index
        units += character_units
    return len(text)


def _chunk_text(text: str, limit: int = _MAX_MESSAGE_LENGTH) -> list[str]:
    if _utf16_length(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while _utf16_length(remaining) > limit:
        split_at = _prefix_within_utf16_limit(remaining, limit)
        newline_at = remaining.rfind("\n", 0, split_at)
        if newline_at >= 0:
            split_at = newline_at + 1
        if split_at == 0:
            # A single Unicode scalar cannot exceed Telegram's real 4096-unit
            # limit, but retain progress for callers using a smaller test limit.
            split_at = 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


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


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    thread_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    chunks = _chunk_text(text)
    message_id: str | None = None
    for index, chunk in enumerate(chunks):
        payload: dict[str, str | int] = {"chat_id": chat_id, "text": chunk}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        headers = {"Content-Type": "application/json"}
        if idempotency_key:
            # Keep the stable key on the transport boundary for deployments that
            # front Telegram with an idempotency-aware egress proxy. Each chunk
            # of a split message needs its own key so a proxy doesn't dedupe
            # the second half against the first.
            headers["Idempotency-Key"] = f"{idempotency_key}:{index}" if len(chunks) > 1 else idempotency_key
        response = resilient_request(
            "POST",
            f"{_BASE}/bot{bot_token}/sendMessage",
            content=json.dumps(payload).encode(),
            headers=headers,
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
    assert message_id is not None
    return str(message_id)
