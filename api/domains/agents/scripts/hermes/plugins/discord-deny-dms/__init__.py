"""Deny Discord DMs before they can reach the agent runtime."""


def _platform_name(platform) -> str:
    return str(getattr(platform, "value", platform) or "").lower()


def deny_discord_dms(event, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = _platform_name(getattr(source, "platform", ""))
    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    if platform == "discord" and chat_type == "dm":
        return {"action": "skip", "reason": "discord-dm-denied"}
    return None


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", deny_discord_dms)
