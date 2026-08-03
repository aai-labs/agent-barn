"""Deny Slack DMs, with optional per-user allowlist via SLACK_DM_ALLOWED_USERS."""

import asyncio
import os


def _allowed_users() -> frozenset:
    raw = os.getenv("SLACK_DM_ALLOWED_USERS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(u.strip() for u in raw.split(",") if u.strip())


def _platform_name(platform) -> str:
    return str(getattr(platform, "value", platform) or "").lower()


def _cleanup_reaction(event, gateway) -> None:
    if gateway is None:
        return
    source = getattr(event, "source", None)
    channel_id = getattr(source, "chat_id", None)
    message_id = getattr(event, "message_id", None)
    if not channel_id or not message_id:
        return
    adapters = getattr(gateway, "adapters", {}) or {}
    adapter = adapters.get(getattr(source, "platform", None)) or adapters.get("slack")
    if adapter is None:
        return
    reacting_ids = getattr(adapter, "_reacting_message_ids", None)
    if reacting_ids is not None:
        reacting_ids.discard(message_id)
    remove_reaction = getattr(adapter, "_remove_reaction", None)
    if remove_reaction is None:
        return
    try:
        asyncio.get_running_loop().create_task(remove_reaction(channel_id, message_id, "eyes"))
    except RuntimeError:
        return


def deny_slack_dms(event, gateway=None, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = _platform_name(getattr(source, "platform", ""))
    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    if platform != "slack" or chat_type != "dm":
        return None
    user_id = str(getattr(source, "user_id", "") or "")
    if user_id and user_id in _allowed_users():
        return None
    _cleanup_reaction(event, gateway)
    return {"action": "skip", "reason": "slack-dm-denied"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", deny_slack_dms)
