"""Run BOOT.md once per gateway start, which pinned Hermes does not do for us.

Hermes only executes BOOT.md through a `gateway:startup` hook reading
$HERMES_HOME/BOOT.md, and ships no such hook -- BOOT.md appears in zero of its
modules. OpenClaw bundles an equivalent hook, so without this every Hermes agent
silently skips the boot checklist its template relies on (idempotent cron
maintenance, in particular).

Driving /v1/runs rather than a hook keeps this off Hermes internals: it is the same
public surface the communications adapter already uses.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app/config")

from agentbarn_message import BOOT_SESSION_ID  # ty: ignore[unresolved-import]

BOOT_FILE = Path("/workspace/BOOT.md")
READY_TIMEOUT_SECONDS = 300


def _post(path: str, payload: dict) -> dict | None:
    request = urllib.request.Request(
        f"{os.environ['RUNTIME_API_URL'].rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['RUNTIME_API_KEY']}",
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": BOOT_SESSION_ID,
            "X-Hermes-Session-Key": BOOT_SESSION_ID,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        body = response.read()
        return json.loads(body) if body else None


def main() -> None:
    instructions = BOOT_FILE.read_text().strip() if BOOT_FILE.exists() else ""
    # Run whatever is there, like OpenClaw's bundled hook does. Guessing which BOOT.md
    # is "real" would risk skipping a genuine one, which is the bug this exists to fix.
    if not instructions:
        print("[boot-run] no BOOT.md; nothing to run", flush=True)
        return

    last: Exception | None = None
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            started = _post(
                "/v1/runs",
                {
                    "input": (
                        "Startup checklist. This runs on every gateway start, so repair or update what "
                        "already exists -- scheduled jobs in particular -- and never create a duplicate. "
                        "Follow the BOOT.md instructions below exactly, then reply with the silent token "
                        f"NO_REPLY.\n\n{instructions}"
                    ),
                    "session_id": BOOT_SESSION_ID,
                    "resume_session": False,
                },
            )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            time.sleep(3)
            last = exc
        else:
            # Fire-and-forget: this only proves the run started, not that the checklist succeeded.
            run_id = (started or {}).get("run_id") or (started or {}).get("id") or "unknown"
            print(f"[boot-run] BOOT.md run {run_id} started; its outcome is in the gateway log", flush=True)
            return
    print(f"[boot-run] gateway never became ready ({type(last).__name__}); BOOT.md not run", flush=True)


if __name__ == "__main__":
    main()
