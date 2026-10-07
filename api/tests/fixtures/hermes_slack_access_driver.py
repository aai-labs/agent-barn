"""Prove independent Slack channel and DM admission in the pinned Hermes image.

Usage: python hermes_slack_access_driver.py IMAGE
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

MESSAGES = [
    ("listed DM", "im", "D1", "U1", "hello"),
    ("unlisted DM", "im", "D2", "U2", "hello"),
    ("channel mention", "channel", "C1", "U2", "<@UBOT> hello"),
    ("other channel mention", "channel", "C2", "U1", "<@UBOT> hello"),
    ("channel without mention", "channel", "C1", "U2", "hello"),
]


def host(image: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from api.domains.agents.builders.hermes import (
        build_hermes_config_map,
        build_hermes_gateway_config,
        native_slack_env,
    )

    for group_policy, channels in [("open", []), ("allowlist", ["C1"]), ("allowlist", [])]:
        for dm_policy, users in [("off", []), ("open", []), ("allowlist", ["U1"]), ("allowlist", [])]:
            settings = {
                "group_policy": group_policy,
                "channel_ids": channels,
                "dm_policy": dm_policy,
                "dm_user_ids": users,
            }
            expected = set()
            if dm_policy == "open":
                expected.update(["listed DM", "unlisted DM"])
            elif dm_policy == "allowlist" and users:
                expected.add("listed DM")
            if group_policy == "open":
                expected.update(["channel mention", "other channel mention"])
            elif channels:
                expected.add("channel mention")
            config = build_hermes_gateway_config("m/m", "http://x", native_slack=True)
            data = build_hermes_config_map(UUID(int=1), UUID(int=2), "test", "", "", "", "", "", "", "", config).data
            env = native_slack_env(settings, {"bot_token": "xoxb-test", "app_token": "xapp-test"})
            with TemporaryDirectory() as directory:
                for name, content in data.items():
                    Path(directory, name).write_text(content)
                subprocess.run(
                    [
                        "docker", "run", "--rm", "--network", "none",
                        *[arg for key, value in env.items() for arg in ("-e", f"{key}={value}")],
                        "-e", f"SLACK_CASE={json.dumps({'settings': settings, 'expected': sorted(expected)})}",
                        "-v", f"{directory}:/config:ro",
                        "-v", f"{Path(__file__).resolve()}:/driver.py:ro",
                        "--entrypoint", "python3", image, "/driver.py", "--check",
                    ],
                    check=True,
                )  # fmt: skip
    print("hermes slack access contract ok")


def check() -> None:
    import asyncio
    import tempfile
    from unittest.mock import AsyncMock

    home = Path(tempfile.mkdtemp())
    os.environ["HERMES_HOME"] = str(home)
    (home / "config.yaml").write_text(Path("/config/hermes-config.yaml").read_text())
    # Materialize the same ConfigMap plugin pair that start.sh installs.
    if Path("/config/slack-access-init.py").exists():
        plugin = home / "plugins" / "agentbarn-slack-access"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text(Path("/config/slack-access-init.py").read_text())
        (plugin / "plugin.yaml").write_text(Path("/config/slack-access-plugin.yaml").read_text())
    sys.path.insert(0, "/opt/hermes")
    from gateway.config import Platform, load_gateway_config  # ty: ignore[unresolved-import]
    from gateway.pairing import PairingStore  # ty: ignore[unresolved-import]
    from gateway.run import GatewayRunner  # ty: ignore[unresolved-import]
    from hermes_cli.plugins import discover_plugins  # ty: ignore[unresolved-import]
    from plugins.platforms.slack.adapter import SlackAdapter  # ty: ignore[unresolved-import]

    discover_plugins()
    config = load_gateway_config()
    adapter = SlackAdapter(config.platforms[Platform.SLACK])
    adapter._bot_user_id = "UBOT"
    adapter._client = AsyncMock()
    adapter._client.users_info.return_value = {"user": {"name": "test", "is_bot": False}}
    adapter._client.conversations_info.return_value = {"channel": {"name": "test"}}
    got = set()

    class AdmissionRunner(GatewayRunner):
        async def receive(self, event):
            if self._is_user_authorized(event.source):
                got.add(event.message_id)

    runner = object.__new__(AdmissionRunner)
    runner.config = config
    runner.adapters = {Platform.SLACK: adapter}
    runner.pairing_store = PairingStore()
    adapter._message_handler = runner.receive

    async def replay():
        for label, channel_type, channel, user, text in MESSAGES:
            await adapter._handle_slack_message(
                {
                    "type": "message",
                    "channel_type": channel_type,
                    "channel": channel,
                    "user": user,
                    "text": text,
                    "ts": label,
                }
            )

    asyncio.run(replay())
    case = json.loads(os.environ["SLACK_CASE"])
    if got != set(case["expected"]):
        raise SystemExit(
            f"Slack access broken for {case['settings']}: received {sorted(got)}, expected {case['expected']}"
        )
    # Native/global grants must not widen the Connection policy. Buttons use
    # the same early authorization seam, even without ordinary message intake.
    os.environ["GATEWAY_ALLOW_ALL_USERS"] = "true"
    os.environ["SLACK_ALLOW_ALL_USERS"] = "true"
    os.environ["SLACK_ALLOWED_USERS"] = "U1,U2"
    for label, _, channel, user, _ in MESSAGES:
        expected = ("channel mention" if label == "channel without mention" else label) in case["expected"]
        actual = adapter._is_interactive_user_authorized(user, channel_id=channel)
        if actual != expected:
            raise SystemExit(f"Slack interactive access broken for {case['settings']}: {label} allowed={actual}")
    # Other Platforms retain Hermes' original authorization behavior.
    from gateway.session import SessionSource  # ty: ignore[unresolved-import]

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm", user_id="123")
    if not runner._is_user_authorized(source):
        raise SystemExit("Slack policy changed another Platform's authorization")
    print(f"PASS {case['settings']}")


if __name__ == "__main__":
    check() if sys.argv[1] == "--check" else host(sys.argv[1])
