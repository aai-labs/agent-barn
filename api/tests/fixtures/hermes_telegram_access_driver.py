"""Prove the native Telegram access mapping against Hermes' real Telegram adapter.

Hermes authorizes a Telegram sender if any of several gates admits them, so the
builder's env and config are only correct in combination. The host half renders
each Connection policy through the real builders; the in-image half (``--check``)
feeds messages through the pinned adapter's mention gate, intake prefilter, and
the gateway's authorization chain.

Usage: ``python hermes_telegram_access_driver.py IMAGE``. Exits non-zero when a
message is admitted or dropped against the Connection's policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GROUP_A, GROUP_B = "-1001", "-1002"
LISTED_USER, OTHER_USER = "111", "222"

# (label, chat type, chat id, sender, how it addresses the bot: "mention", "reply", or None)
MESSAGES = [
    ("dm listed user", "private", LISTED_USER, LISTED_USER, None),
    ("dm other user", "private", OTHER_USER, OTHER_USER, None),
    ("group A mention", "supergroup", GROUP_A, OTHER_USER, "mention"),
    ("group A reply to bot", "supergroup", GROUP_A, OTHER_USER, "reply"),
    ("group A no mention", "supergroup", GROUP_A, OTHER_USER, None),
    ("group B mention by listed user", "supergroup", GROUP_B, LISTED_USER, "mention"),
]

# Connection settings -> the labels that must be admitted; every other message must not be.
CASES = [
    ({}, set()),
    ({"allowed_chat_ids": [GROUP_A]}, {"group A mention", "group A reply to bot"}),
    ({"dm_policy": "open"}, {"dm listed user", "dm other user"}),
    # A blank chat ID is no allowlist, not "any group".
    ({"dm_policy": "open", "allowed_chat_ids": [""]}, {"dm listed user", "dm other user"}),
    # Closed groups drop a listed DM sender who mentions the bot in a group.
    ({"dm_policy": "allowlist", "allowed_user_ids": [LISTED_USER]}, {"dm listed user"}),
    (
        {"dm_policy": "allowlist", "allowed_user_ids": [LISTED_USER], "group_policy": "open"},
        {"dm listed user", "group A mention", "group A reply to bot", "group B mention by listed user"},
    ),
    (
        {"dm_policy": "allowlist", "allowed_user_ids": [LISTED_USER], "allowed_chat_ids": [GROUP_A]},
        {"dm listed user", "group A mention", "group A reply to bot"},
    ),
]


def host(image: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from api.domains.agents.builders.hermes import build_hermes_gateway_config, native_telegram_env

    for settings, admitted in CASES:
        config = build_hermes_gateway_config("m/m", "http://x", telegram_settings=settings)
        env = native_telegram_env(settings, {"bot_token": "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"})
        env_args = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]
        subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none", *env_args,
                "-e", f"TELEGRAM_CASE={json.dumps({'telegram': config['telegram'], 'admitted': sorted(admitted)})}",
                "-v", f"{Path(__file__).resolve()}:/driver.py:ro",
                "--entrypoint", "python3", image, "/driver.py", "--check",
            ],
            check=True,
        )  # fmt: skip
    print("hermes telegram access contract ok")


def check() -> None:
    import tempfile
    from types import SimpleNamespace

    import yaml

    case = json.loads(os.environ["TELEGRAM_CASE"])
    home = Path(tempfile.mkdtemp())
    os.environ["HERMES_HOME"] = str(home)
    (home / "config.yaml").write_text(yaml.dump({"telegram": case["telegram"]}))
    sys.path.insert(0, "/opt/hermes")

    # Only resolvable inside the Hermes image, which is the only place this runs.
    from gateway.config import Platform, load_gateway_config  # ty: ignore[unresolved-import]
    from gateway.pairing import PairingStore  # ty: ignore[unresolved-import]
    from gateway.run import GatewayRunner  # ty: ignore[unresolved-import]
    from plugins.platforms.telegram.adapter import TelegramAdapter  # ty: ignore[unresolved-import]

    config = load_gateway_config()
    adapter = TelegramAdapter(config.platforms[Platform.TELEGRAM])
    adapter._bot = SimpleNamespace(id=42, username="agent_bot")
    # Bare runner, as Hermes' own tests build it; only authorization is exercised.
    runner = object.__new__(GatewayRunner)
    runner.config = config
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.pairing_store = PairingStore()
    adapter._message_handler = runner._is_user_authorized  # the adapter finds its runner via __self__

    got = set()
    for label, chat_type, chat_id, sender, addressed in MESSAGES:
        mention = addressed == "mention"
        message = SimpleNamespace(
            chat=SimpleNamespace(id=int(chat_id), type=chat_type, is_forum=False, title="chat"),
            from_user=SimpleNamespace(id=int(sender), username="user", full_name="User", is_bot=False),
            sender_chat=None,
            text="@agent_bot hi" if mention else "hi",
            entities=[SimpleNamespace(type="mention", offset=0, length=10)] if mention else [],
            caption=None,
            caption_entities=[],
            message_thread_id=None,
            is_topic_message=False,
            reply_to_message=(
                SimpleNamespace(from_user=adapter._bot, message_id=0, text="earlier reply")
                if addressed == "reply"
                else None
            ),
            message_id=1,
        )
        if (
            adapter._should_process_message(message)
            and adapter._is_user_authorized_from_message(message)
            and runner._is_user_authorized(adapter._source_from_message_for_auth(message))
        ):
            got.add(label)
    if got != set(case["admitted"]):
        raise SystemExit(
            f"telegram access contract broken for {case['telegram']}: admitted {sorted(got)}, expected {case['admitted']}"
        )


if __name__ == "__main__":
    check() if sys.argv[1] == "--check" else host(sys.argv[1])
