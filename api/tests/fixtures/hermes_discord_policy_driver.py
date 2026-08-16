"""Exercise Discord policy hooks against Hermes' real gateway event source type."""

import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, "/opt/hermes")

from gateway.config import Platform  # ty: ignore[unresolved-import]
from gateway.session import SessionSource  # ty: ignore[unresolved-import]


def load_hook(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    loader = spec.loader if spec else None
    if spec is None or loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    hooks = {}
    context = MagicMock()
    context.register_hook.side_effect = lambda name, hook: hooks.update({name: hook})
    module.register(context)
    try:
        return hooks["pre_gateway_dispatch"]
    except KeyError as exc:
        raise SystemExit(f"{module_name} did not register pre_gateway_dispatch") from exc


def event(*, chat_type: str, guild_id: str | None = None):
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-1",
        chat_type=chat_type,
        user_id="user-1",
        guild_id=guild_id,
    )
    return SimpleNamespace(text="hello", source=source, message_id="message-1")


def main() -> None:
    deny_dms = load_hook("discord_deny_dms", "/plugins/deny-dms/__init__.py")
    guild_allowlist = load_hook("discord_guild_allowlist", "/plugins/guild-allowlist/__init__.py")

    denied_dm = deny_dms(event=event(chat_type="dm"))
    if denied_dm != {"action": "skip", "reason": "discord-dm-denied"}:
        raise SystemExit(f"Discord DM hook failed closed incorrectly: {denied_dm}")

    os.environ["DISCORD_GUILD_IDS"] = "guild-1"
    if guild_allowlist(event=event(chat_type="channel", guild_id="guild-1")) is not None:
        raise SystemExit("Discord guild hook denied an allowlisted guild")
    denied_guild = guild_allowlist(event=event(chat_type="channel", guild_id="guild-2"))
    if denied_guild != {"action": "skip", "reason": "discord-guild-not-allowlisted"}:
        raise SystemExit(f"Discord guild hook failed closed incorrectly: {denied_guild}")

    os.environ["DISCORD_GUILD_IDS"] = ""
    denied_empty = guild_allowlist(event=event(chat_type="channel", guild_id="guild-1"))
    if denied_empty != {"action": "skip", "reason": "discord-guild-not-allowlisted"}:
        raise SystemExit("Discord guild hook did not fail closed for an empty allowlist")

    print("hermes Discord policy contract ok")


if __name__ == "__main__":
    main()
