"""Prove the WhatsApp Connection access mapping against Hermes' real bridge, adapter and gateway.

A WhatsApp message passes three gates: the Node bridge's sender allowlist, the
adapter's DM/group policy at intake, and the gateway's authorization chain. The
builder's env and config are only correct in combination. The host half renders
each Connection policy through the real builders; the in-image half (``--check``)
puts messages through all three.

Usage: ``python hermes_whatsapp_access_driver.py IMAGE``. Exits non-zero when a
message is admitted or dropped against the Connection's policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LISTED, OTHER, BOT = "15551234567", "15559990000", "15550001111"
GROUP_A, GROUP_B = "120363000000000001@g.us", "120363000000000002@g.us"

# (label, chat id, sender number, mentions the bot)
MESSAGES = [
    ("dm listed", f"{LISTED}@s.whatsapp.net", LISTED, False),
    ("dm other", f"{OTHER}@s.whatsapp.net", OTHER, False),
    ("group A mention", GROUP_A, OTHER, True),
    ("group A no mention", GROUP_A, OTHER, False),
    ("group B mention by listed", GROUP_B, LISTED, True),
]

_DEFAULTS = {
    "dm_policy": "allowlist",
    "allowed_numbers": [LISTED],
    "group_policy": "off",
    "allowed_group_ids": [],
    "require_mention": True,
}

# Connection settings -> the labels that must be admitted; every other message must not be.
CASES = [
    ({}, {"dm listed"}),
    ({"allowed_numbers": []}, set()),
    ({"dm_policy": "open"}, {"dm listed", "dm other"}),
    ({"dm_policy": "off", "group_policy": "allowlist", "allowed_group_ids": [GROUP_A]}, {"group A mention"}),
    # Opening groups must not open DMs to senders outside the allowlist.
    ({"group_policy": "open"}, {"dm listed", "group A mention", "group B mention by listed"}),
    (
        {"dm_policy": "off", "group_policy": "open", "require_mention": False},
        {"group A mention", "group A no mention", "group B mention by listed"},
    ),
    # Self Chat ignores the access settings and never answers in groups. The bridge's
    # self-chat mode then passes only the owner's own chat, so these DMs never arrive.
    (
        {"mode": "self_chat", "dm_policy": "off", "allowed_numbers": [], "group_policy": "open"},
        {"dm listed", "dm other"},
    ),
]


def host(image: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from api.domains.agents.builders.hermes import build_hermes_gateway_config, native_whatsapp_env

    for overrides, admitted in CASES:
        settings = {**_DEFAULTS, **overrides}
        config = build_hermes_gateway_config("m/m", "http://x", whatsapp_settings=settings)
        env = native_whatsapp_env(settings)
        env_args = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]
        platforms = {"whatsapp": config["platforms"]["whatsapp"]}
        subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none", *env_args,
                "-e", f"WHATSAPP_CASE={json.dumps({'platforms': platforms, 'admitted': sorted(admitted)})}",
                "-v", f"{Path(__file__).resolve()}:/driver.py:ro",
                "--entrypoint", "python3", image, "/driver.py", "--check",
            ],
            check=True,
        )  # fmt: skip
    print("hermes whatsapp access contract ok")


def _bridge_admits(sender: str) -> bool:
    script = (
        "const m = await import('/opt/hermes/scripts/whatsapp-bridge/allowlist.js');"
        "const allowed = m.parseAllowedUsers(process.env.WHATSAPP_ALLOWED_USERS || '');"
        f"process.exit(m.matchesAllowedUser('{sender}@s.whatsapp.net', allowed, '/tmp') ? 0 : 1);"
    )
    return subprocess.run(["node", "--input-type=module", "-e", script], check=False).returncode == 0


def check() -> None:
    import tempfile

    import yaml

    case = json.loads(os.environ["WHATSAPP_CASE"])
    home = Path(tempfile.mkdtemp())
    os.environ["HERMES_HOME"] = str(home)
    (home / "config.yaml").write_text(yaml.dump({"platforms": case["platforms"]}))
    sys.path.insert(0, "/opt/hermes")

    # Only resolvable inside the Hermes image, which is the only place this runs.
    from gateway.config import Platform, load_gateway_config  # ty: ignore[unresolved-import]
    from gateway.pairing import PairingStore  # ty: ignore[unresolved-import]
    from gateway.run import GatewayRunner  # ty: ignore[unresolved-import]
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter  # ty: ignore[unresolved-import]

    config = load_gateway_config()
    adapter = WhatsAppAdapter(config.platforms[Platform.WHATSAPP])
    # Bare runner, as Hermes' own tests build it; only authorization is exercised.
    runner = object.__new__(GatewayRunner)
    runner.config = config
    runner.adapters = {Platform.WHATSAPP: adapter}
    runner.pairing_store = PairingStore()

    got = set()
    for label, chat_id, sender, mentions in MESSAGES:
        is_group = chat_id.endswith("@g.us")
        data = {
            "chatId": chat_id,
            "isGroup": is_group,
            "senderId": f"{sender}@s.whatsapp.net",
            "body": f"@{BOT} hi" if mentions else "hi",
            "botIds": [f"{BOT}@s.whatsapp.net"],
            "mentionedIds": [f"{BOT}@s.whatsapp.net"] if mentions else [],
        }
        source = adapter.build_source(
            chat_id=chat_id, chat_type="group" if is_group else "dm", user_id=data["senderId"]
        )
        if _bridge_admits(sender) and adapter._should_process_message(data) and runner._is_user_authorized(source):
            got.add(label)
    if got != set(case["admitted"]):
        raise SystemExit(
            f"whatsapp access contract broken for {case['platforms']}: "
            f"admitted {sorted(got)}, expected {case['admitted']}"
        )


if __name__ == "__main__":
    check() if sys.argv[1] == "--check" else host(sys.argv[1])
