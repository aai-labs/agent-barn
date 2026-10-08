import json
import logging
import re
from typing import Any

import httpx

from api.core.config import get_config
from api.infrastructure.http import resilient_request

# Bot API URLs carry the token in their path (/bot<id>:<secret>/method); clients
# may percent-encode the colon, and access logs print the path as sent.
_BOT_TOKEN_IN_URL = re.compile(r"/bot\d+(?::|%3[Aa])[A-Za-z0-9_-]+")


class RedactBotTokens(logging.Filter):
    """Keep Telegram bot tokens, real or stand-in, out of log lines that print request URLs."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact inside the arguments rather than flattening them: formatters such
        # as uvicorn's AccessFormatter unpack record.args by position.
        if isinstance(record.args, tuple):
            record.args = tuple(_redacted(arg) for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = _BOT_TOKEN_IN_URL.sub("/bot<redacted>", record.msg)
        return True


def _redacted(arg: object) -> object:
    """The argument with any bot token removed, keeping its type when it has none (for %d and the like)."""
    text = str(arg)
    return _BOT_TOKEN_IN_URL.sub("/bot<redacted>", text) if _BOT_TOKEN_IN_URL.search(text) else arg


logging.getLogger("httpx").addFilter(RedactBotTokens())

_BASE = "https://api.telegram.org"
_TIMEOUT_SECONDS = 15


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


class TelegramPollError(RuntimeError):
    """A failed getUpdates call, described without the URL that carries the bot token."""


async def get_updates(
    client: httpx.AsyncClient,
    bot_token: str,
    *,
    offset: int | None,
    timeout_seconds: int,
    allowed_updates: list[str],
) -> list[dict[str, Any]]:
    """Long-poll Telegram once; every update below ``offset`` is confirmed as received."""
    params: dict[str, Any] = {"timeout": timeout_seconds, "allowed_updates": json.dumps(allowed_updates)}
    if offset is not None:
        params["offset"] = offset
    try:
        response = await client.get(f"{_BASE}/bot{bot_token}/getUpdates", params=params)
    except httpx.HTTPError as exc:
        # httpx errors carry the request URL, and with it the token.
        raise TelegramPollError(f"Telegram getUpdates failed ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise TelegramPollError(f"Telegram getUpdates failed (HTTP {response.status_code})")
    body = response.json()
    if not body.get("ok"):
        raise TelegramPollError(f"Telegram getUpdates error: {body.get('description', 'unknown error')}")
    return [update for update in body.get("result", []) if isinstance(update, dict)]
