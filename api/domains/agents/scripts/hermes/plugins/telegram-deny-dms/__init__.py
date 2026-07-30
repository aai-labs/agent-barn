"""Deny Telegram DMs, with optional per-user allowlist via TELEGRAM_DM_ALLOWED_USERS."""

import os


def _allowed_users() -> frozenset:
    raw = os.getenv("TELEGRAM_DM_ALLOWED_USERS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(u.strip() for u in raw.split(",") if u.strip())


def _platform_name(platform) -> str:
    return str(getattr(platform, "value", platform) or "").lower()


def deny_telegram_dms(event, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = _platform_name(getattr(source, "platform", ""))
    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    if platform != "telegram" or chat_type != "dm":
        return None
    user_id = str(getattr(source, "user_id", "") or "")
    if user_id and user_id in _allowed_users():
        return None
    return {"action": "skip", "reason": "telegram-dm-denied"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", deny_telegram_dms)
