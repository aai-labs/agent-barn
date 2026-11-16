"""Prove the workflow approval DM click path in the pinned Hermes image.

Loads the agentbarn-workflow-approvals plugin through Hermes's plugin discovery,
wires its public Slack action handlers into a real slack_bolt AsyncApp the way
the Slack adapter does at connect time, dispatches Socket Mode block_actions
payloads, and checks which clicks reach a stub trigger server.

Usage: python hermes_workflow_approval_driver.py IMAGE
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APPROVER = "UAPPROVER"
REQUEST_ID = "6f1c2c7e-6b1f-4d0a-9a43-2f8f0b9a1c11"


def host(image: str) -> None:
    plugin = Path(__file__).resolve().parents[2] / "domains/agents/scripts/hermes/plugins/agentbarn-workflow-approvals"
    subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none",
            "-e", f"AGENTBARN_SLACK_APPROVAL_USER={APPROVER}",
            "-e", "AGENT_TRIGGER_KEY=trigger-key",
            "-e", "AGENT_TRIGGER_PORT=18082",
            "-v", f"{plugin}:/plugin:ro",
            "-v", f"{Path(__file__).resolve()}:/driver.py:ro",
            "--entrypoint", "python3", image, "/driver.py", "--check",
        ],
        check=True,
    )  # fmt: skip
    print("hermes workflow approval contract ok")


def check() -> None:
    import asyncio
    import json
    import os
    import shutil
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    home = Path(tempfile.mkdtemp())
    os.environ["HERMES_HOME"] = str(home)
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - agentbarn-workflow-approvals\n")
    shutil.copytree("/plugin", home / "plugins" / "agentbarn-workflow-approvals")
    sys.path.insert(0, "/opt/hermes")
    from hermes_cli.plugins import discover_plugins, get_plugin_manager  # ty: ignore[unresolved-import]
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.request.async_request import AsyncBoltRequest

    received: list[tuple[str, str, dict]] = []

    class Trigger(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization", ""), body))
            self.send_response(202)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 18082), Trigger)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    discover_plugins()
    handlers = get_plugin_manager().get_slack_action_handlers()
    assert [name for _, _, name in handlers] == ["agentbarn-workflow-approvals"], handlers
    from slack_bolt.authorization import AuthorizeResult

    async def authorize(**_) -> AuthorizeResult:
        # Offline stand-in for the auth.test call a real token triggers.
        return AuthorizeResult(enterprise_id=None, team_id="T1", bot_token="xoxb-test", bot_user_id="UBOT")

    app = AsyncApp(signing_secret="unused", authorize=authorize)
    for action_id, callback, _ in handlers:
        app.action(action_id)(callback)

    async def click(action_id: str, user: str, channel: str, value: str = REQUEST_ID) -> int:
        before = len(received)
        body = {
            "type": "block_actions",
            "team": {"id": "T1"},
            "user": {"id": user, "username": f"{user.lower()}-handle", "name": user.lower()},
            "channel": {"id": channel},
            "message": {"ts": "1700000000.000100"},
            "actions": [{"type": "button", "action_id": action_id, "block_id": "b", "value": value}],
        }
        response = await app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode"))
        return response.status, len(received) - before

    async def run() -> None:
        cases = [
            ("approver approves in DM", "agentbarn_workflow_approval_approve", APPROVER, "D1", REQUEST_ID, 1),
            ("approver declines in DM", "agentbarn_workflow_approval_decline", APPROVER, "D1", REQUEST_ID, 1),
            ("other user", "agentbarn_workflow_approval_approve", "UOTHER", "D2", REQUEST_ID, 0),
            ("approver in a channel", "agentbarn_workflow_approval_approve", APPROVER, "C1", REQUEST_ID, 0),
            ("malformed request id", "agentbarn_workflow_approval_approve", APPROVER, "D1", "not-a-uuid", 0),
        ]
        for label, action_id, user, channel, value, expected in cases:
            status, forwarded = await click(action_id, user, channel, value)
            assert status == 200, (label, status)
            assert forwarded == expected, (label, forwarded)
        # Hermes's own chat approval buttons are not intercepted by this plugin.
        status, forwarded = await click("hermes_approve_once", APPROVER, "D1", "session")
        assert status == 404 and forwarded == 0, (status, forwarded)
        os.environ["AGENTBARN_SLACK_APPROVAL_USER"] = ""
        status, forwarded = await click("agentbarn_workflow_approval_approve", APPROVER, "D1")
        assert status == 200 and forwarded == 0, ("unset approver", forwarded)

    asyncio.run(run())
    path, authorization, body = received[0]
    assert path == f"/agent-triggers/v1/workflow-approvals/{REQUEST_ID}/slack-decision", path
    assert authorization == "Bearer trigger-key", authorization
    assert body == {
        "decision": "approve",
        "slack_user_id": APPROVER,
        "slack_user_name": "uapprover-handle",
        "channel_id": "D1",
        "message_ts": "1700000000.000100",
    }, body
    assert received[1][2]["decision"] == "decline", received[1]
    server.shutdown()
    print(f"PASS {len(received)} forwarded clicks")


if __name__ == "__main__":
    check() if sys.argv[1] == "--check" else host(sys.argv[1])
