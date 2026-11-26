"""Prove the WhatsApp Connection access mapping against OpenClaw's pinned access decisions.

The host half renders each Connection policy through the real builder; the in-image
half (``openclaw_whatsapp_access_check.mjs``) puts messages through OpenClaw's sender
access, group allowlist and mention rule. Bot-mode cases are the Hermes contract's own,
so both runtimes must admit the same messages for the same Connection.

Usage: ``python openclaw_whatsapp_access_driver.py IMAGE``. Exits non-zero when a
message is admitted or dropped against the Connection's policy.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from api.domains.agents.builders.openclaw import native_whatsapp_channel
from hermes_whatsapp_access_driver import _DEFAULTS, BOT, CASES, LISTED, MESSAGES

# OpenClaw sees the owner's own messages too; Bot mode must ignore them.
OWN_CHAT = ("dm self", f"{BOT}@s.whatsapp.net", BOT, False)

OPENCLAW_CASES = [
    *[(overrides, admitted) for overrides, admitted in CASES if overrides.get("mode") != "self_chat"],
    # Self Chat answers only the owner's Message yourself chat, whatever the access settings say.
    ({"mode": "self_chat", "dm_policy": "open", "group_policy": "open", "allowed_numbers": [LISTED]}, {"dm self"}),
]


def main(image: str) -> None:
    messages = [
        {"label": label, "chat": chat, "sender": sender, "mentions": mentions}
        for label, chat, sender, mentions in [*MESSAGES, OWN_CHAT]
    ]
    cases = [
        {"channel": native_whatsapp_channel({**_DEFAULTS, **overrides}), "admitted": sorted(admitted)}
        for overrides, admitted in OPENCLAW_CASES
    ]
    subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none",
            "-e", f"WHATSAPP_CASES={json.dumps({'self': BOT, 'messages': messages, 'cases': cases})}",
            "-v", f"{HERE / 'openclaw_whatsapp_access_check.mjs'}:/check.mjs:ro",
            "--entrypoint", "node", image, "/check.mjs",
        ],
        check=True,
    )  # fmt: skip
    print("openclaw whatsapp access contract ok")


if __name__ == "__main__":
    main(sys.argv[1])
