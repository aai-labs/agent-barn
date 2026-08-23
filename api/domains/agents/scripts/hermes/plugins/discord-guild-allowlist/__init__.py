"""Restrict Discord server messages to DISCORD_GUILD_IDS.

An empty allowlist denies every guild. DMs are handled by discord-deny-dms.
"""

import os


def _allowed_guilds() -> frozenset:
    raw = os.getenv("DISCORD_GUILD_IDS", "").strip()
    return frozenset(value.strip() for value in raw.split(",") if value.strip())


def _platform_name(platform) -> str:
    return str(getattr(platform, "value", platform) or "").lower()


def filter_guild(event, **kwargs):
    source = getattr(event, "source", None)
    if source is None or _platform_name(getattr(source, "platform", "")) != "discord":
        return None
    if str(getattr(source, "chat_type", "") or "").lower() == "dm":
        return None

    guild_id = str(getattr(source, "guild_id", "") or "")
    if not guild_id or guild_id not in _allowed_guilds():
        return {"action": "skip", "reason": "discord-guild-not-allowlisted"}
    return None


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", filter_guild)
