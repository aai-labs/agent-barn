"""Make Hermes's Honcho recall pool-wide (AF-280 shared memory pools).

Upstream `dialectic_query` recalls only THIS agent's own view: its `_chat_once`
queries the agent's own peer (`ai_peer.chat(target=user)`) or the user's own
self-view. In a shared memory pool every agent must see what the WHOLE pool
knows, so we replace `_chat_once` to query Honcho's workspace-level dialectic
(`POST /v3/workspaces/{ws}/chat`), which aggregates across every peer. It reuses
the SDK client's own transport (base URL + auth), and the workspace is already
the shared pool (set by our builder) — so nothing else changes.

Anchored on the function's ASCII start/end lines and fails the build on source
drift, so a Hermes upgrade forces a review of this patch.
"""

import re
import sys
from pathlib import Path

TARGET = "/opt/hermes/plugins/memory/honcho/session.py"

# Marker that proves the patch is already applied (idempotent re-runs).
MARKER = "AF-280: pool-wide recall"

# Match the whole upstream _chat_once: from its def line through its final
# return. The middle contains a non-ASCII em-dash comment, so match the body
# generically (indented lines) and pin only the stable ASCII start/end lines.
PATTERN = re.compile(
    r"        def _chat_once\(\) -> str:\n"
    r"(?:(?:            .*|                .*|)\n)*?"
    r'            return target_peer\.chat\(query, reasoning_level=level\) or ""\n'
)

REPLACEMENT = (
    "        def _chat_once() -> str:\n"
    "            # AF-280: pool-wide recall. Upstream queries only this agent's\n"
    "            # own view (observer = its own peer); in a shared memory pool\n"
    "            # every agent should see what the whole pool knows, so query the\n"
    "            # workspace-level dialectic, which aggregates across all peers.\n"
    "            # Reuses the SDK client's transport (base URL + auth).\n"
    '            body: dict = {"query": query, "stream": False, "target": target_peer_id}\n'
    "            if level:\n"
    '                body["reasoning_level"] = level\n'
    "            self.honcho._ensure_workspace()\n"
    "            data = self.honcho._http.post(\n"
    '                f"/v3/workspaces/{self.honcho.workspace_id}/chat", body=body\n'
    "            )\n"
    "            if isinstance(data, dict):\n"
    '                return data.get("content") or ""\n'
    '            return ""\n'
)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(TARGET)
    source = target.read_text()
    if MARKER in source:
        return
    matches = PATTERN.findall(source)
    if len(matches) != 1:
        raise SystemExit(
            f"Hermes _chat_once source changed (found {len(matches)} matches); "
            "review the pool-wide recall patch"
        )
    patched = PATTERN.sub(REPLACEMENT, source, count=1)
    compile(patched, str(target), "exec")
    target.write_text(patched)


if __name__ == "__main__":
    main()
