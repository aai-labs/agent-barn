"""Restrict responses to channels listed in SLACK_CHANNEL_IDS.

If SLACK_CHANNEL_IDS is empty, the agent responds in all channels.
DMs are not affected — those are handled by slack-deny-dms.
"""

import os


def _allowed_channels() -> frozenset:
    raw = os.getenv("SLACK_CHANNEL_IDS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


def _platform_name(platform) -> str:
    return str(getattr(platform, "value", platform) or "").lower()


def filter_channel(event, **kwargs):
    allowed = _allowed_channels()
    if not allowed:
        return None  # no allowlist — respond everywhere

    source = getattr(event, "source", None)
    if source is None:
        return None

    if _platform_name(getattr(source, "platform", "")) != "slack":
        return None

    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    if chat_type == "dm":
        return None  # leave DMs to slack-deny-dms

    channel_id = str(getattr(source, "chat_id", "") or "")
    if channel_id not in allowed:
        return {"action": "skip", "reason": "channel-not-allowlisted"}

    return None


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", filter_channel)
