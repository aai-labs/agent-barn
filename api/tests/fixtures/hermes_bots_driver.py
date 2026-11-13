from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.secret_scope import (  # ty: ignore[unresolved-import]
    build_profile_secret_scope,
    reset_secret_scope,
    set_multiplex_active,
    set_secret_scope,
)
from cron.scheduler_provider import InProcessCronScheduler  # ty: ignore[unresolved-import]
from gateway.authz_mixin import _platform_gate_env  # ty: ignore[unresolved-import]
from gateway.config import GatewayConfig, Platform, PlatformConfig, load_gateway_config  # ty: ignore[unresolved-import]
from gateway.delivery import resolve_delivery_transport  # ty: ignore[unresolved-import]
from gateway.platform_registry import platform_registry  # ty: ignore[unresolved-import]
from hermes_cli.profiles import validate_profile_name  # ty: ignore[unresolved-import]
from hermes_constants import (  # ty: ignore[unresolved-import]
    get_hermes_home,
    reset_hermes_home_override,
    set_hermes_home_override,
)
from plugins.platforms.discord.adapter import DiscordAdapter  # ty: ignore[unresolved-import]
from tools.env_passthrough import resolve_passthrough_value  # ty: ignore[unresolved-import]
from tools.send_message_tool import _send_via_adapter  # ty: ignore[unresolved-import]

BOT_A = "aaaaaaaa-0000-4000-8000-00000000000a"
BOT_B = "bbbbbbbb-0000-4000-8000-00000000000b"


def home(root: Path, name: str, env: dict[str, str]) -> Path:
    path = root / "profiles" / name
    path.mkdir(parents=True)
    (path / ".env").write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    (path / "config.yaml").write_text("platforms:\n  api_server:\n    enabled: false\n")
    return path


def check(label: str, condition: bool) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    print(f"ok: {label}")


def in_scope(path: Path, read):
    token = set_secret_scope(build_profile_secret_scope(path))
    try:
        return read()
    finally:
        reset_secret_scope(token)


def main() -> None:
    root = Path(tempfile.mkdtemp())
    first = home(
        root,
        BOT_A,
        {
            "ARTIFACT_API_KEY": "key-a",
            "ONLY_A": "a",
            "SLACK_BOT_TOKEN": "xoxb-a",
            "SLACK_APP_TOKEN": "xapp-a",
            "DISCORD_ALLOWED_USERS": "111",
        },
    )
    second = home(
        root,
        BOT_B,
        {
            "ARTIFACT_API_KEY": "key-b",
            "SLACK_BOT_TOKEN": "xoxb-b",
            "SLACK_APP_TOKEN": "xapp-b",
            "DISCORD_ALLOWED_USERS": "222",
        },
    )
    os.environ.update({"ARTIFACT_API_KEY": "", "ONLY_A": "", "AGENTBARN_SLACK_DM_POLICY": "open"})
    set_multiplex_active(True)

    check("a Bot's id is a valid profile name", validate_profile_name(BOT_A) is None)

    def read_key() -> str | None:
        return resolve_passthrough_value("ARTIFACT_API_KEY", "")

    check("passthrough reads the first Bot's value", in_scope(first, read_key) == "key-a")
    check("passthrough reads the second Bot's value", in_scope(second, read_key) == "key-b")
    check(
        "a name another Bot holds does not reach this Bot",
        not in_scope(second, lambda: resolve_passthrough_value("ONLY_A", "")),
    )

    check(
        "the Slack gate never falls through to process env",
        in_scope(first, lambda: _platform_gate_env("AGENTBARN_SLACK_DM_POLICY", "off")) == "off",
    )

    plugin = Path("/slack-access/__init__.py")
    spec = importlib.util.spec_from_file_location("slack_access", plugin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.register(MagicMock())
    print("ok: the Slack access plugin registers against this Hermes")

    parent = SimpleNamespace(name="parent adapter")
    shared = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="parent")})
    transport = resolve_delivery_transport(Platform.TELEGRAM, shared, {Platform.TELEGRAM: parent})
    check("delivery uses the connection it is handed", transport.adapter is parent)
    check(
        "a platform with no connection has no live transport",
        resolve_delivery_transport(Platform.SLACK, shared, {Platform.TELEGRAM: parent}) is None,
    )

    bot_connection = SimpleNamespace(name="bot adapter")
    ticked: dict[str, dict] = {}
    stop = threading.Event()

    def record_tick(*, adapters, **_) -> None:
        ticked[get_hermes_home().name] = adapters
        if len(ticked) == 3:
            stop.set()

    safety = threading.Timer(30, stop.set)
    safety.start()
    with patch("cron.scheduler.tick", record_tick):
        InProcessCronScheduler()._start_multiplex(
            stop,
            profile_homes=[("default", root), (BOT_A, first), (BOT_B, second)],
            profile_adapters={BOT_A: {Platform.SLACK: bot_connection}},
            adapters={Platform.SLACK: parent},
            interval=1,
        )
    safety.cancel()
    check("the parent's jobs use the parent's connections", ticked[root.name] == {Platform.SLACK: parent})
    check("a Bot's jobs use that Bot's connections", ticked[BOT_A] == {Platform.SLACK: bot_connection})
    check("a Bot with no connection never gets the parent's", ticked[BOT_B] == {})

    def send_from(path: Path) -> tuple[list[str], list[str]]:
        live: list[str] = []
        standalone: list[str] = []

        async def live_send(*, chat_id, content, metadata):
            live.append(content)
            return SimpleNamespace(success=True, message_id="1")

        async def standalone_send(_config, _chat_id, content, **_):
            standalone.append(content)
            return {"success": True}

        runner = SimpleNamespace(adapters={Platform.SLACK: SimpleNamespace(send=live_send)})
        entry = SimpleNamespace(standalone_sender_fn=standalone_send)
        token = set_hermes_home_override(path)
        try:
            with (
                patch("gateway.run._gateway_runner_ref", lambda: runner),
                patch.object(platform_registry, "get", lambda _name: entry),
            ):
                asyncio.run(_send_via_adapter(Platform.SLACK, None, "C1", "hello"))
        finally:
            reset_hermes_home_override(token)
        return live, standalone

    check("a Bot's fallback send skips the parent's connection", send_from(first) == ([], ["hello"]))
    check("the parent still sends through its own connection", send_from(root) == (["hello"], []))

    def bot_slack_token(path: Path) -> str | None:
        token = set_hermes_home_override(path)
        try:
            platform = load_gateway_config().platforms.get(Platform.SLACK)
            return platform.token if platform else None
        finally:
            reset_hermes_home_override(token)

    check(
        "a Bot's scheduled delivery uses its own credential",
        in_scope(first, lambda: bot_slack_token(first)) == "xoxb-a",
    )
    check("another Bot's delivery uses its own", in_scope(second, lambda: bot_slack_token(second)) == "xoxb-b")

    os.environ.update({"DISCORD_REQUIRE_MENTION": "true", "DISCORD_THREAD_REQUIRE_MENTION": "true"})
    open_bot = DiscordAdapter(
        PlatformConfig(enabled=True, token="a", extra={"require_mention": False, "thread_require_mention": False})
    )
    strict_bot = DiscordAdapter(
        PlatformConfig(enabled=True, token="b", extra={"require_mention": True, "thread_require_mention": True})
    )
    check("a Bot's Discord mention setting beats the process env", not open_bot._discord_require_mention())
    check("a Bot's Discord thread setting beats the process env", not open_bot._discord_thread_require_mention())
    check("another Bot keeps its own Discord mention setting", strict_bot._discord_require_mention())
    in_scope(first, open_bot._snapshot_gate_env)
    in_scope(second, strict_bot._snapshot_gate_env)
    check("a Bot's Discord allow list is its own", open_bot._gate_env("DISCORD_ALLOWED_USERS") == "111")
    check("another Bot's Discord allow list is its own", strict_bot._gate_env("DISCORD_ALLOWED_USERS") == "222")
    open_bot.set_owner_profile(BOT_A)
    strict_bot.set_owner_profile("default")
    check("an adapter names the Bot profile that owns it", open_bot._owner_profile == BOT_A)
    check("the default profile's adapter names no owner", strict_bot._owner_profile is None)
    print("All Bot checks passed")


if __name__ == "__main__":
    sys.exit(main())
