"""Forward workflow approval clicks from the Slack approval DM to the trigger server.

The trigger server posts the card and edits it; this plugin only receives the
card's button clicks through Hermes's public Slack action registry. A click
counts only when it comes from the Connection's configured approver, in a DM.
The trigger server reports it to the API, which records it and decides races;
nothing here answers Hermes directly.
"""

import asyncio
import json
import logging
import os
import re
import urllib.request
from uuid import UUID

ACTIONS = re.compile(r"^agentbarn_workflow_approval_(approve|decline)$")
logger = logging.getLogger(__name__)


def _forward(request_id: str, payload: dict) -> None:
    port = os.environ.get("AGENT_TRIGGER_PORT", "8082")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/agent-triggers/v1/workflow-approvals/{request_id}/slack-decision",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ.get('AGENT_TRIGGER_KEY', '')}",
            "Content-Type": "application/json",
        },
    )
    urllib.request.urlopen(request, timeout=10).close()


def register(ctx):
    async def on_click(ack, body, action):
        await ack()
        approver = os.environ.get("AGENTBARN_SLACK_APPROVAL_USER", "").strip()
        user = body.get("user") or {}
        channel = (body.get("channel") or {}).get("id", "")
        match = ACTIONS.match(action.get("action_id", ""))
        if not approver or not match or user.get("id") != approver or not channel.startswith("D"):
            logger.warning("[agentbarn] ignored workflow approval click from %s in %s", user.get("id"), channel)
            return
        try:
            request_id = str(UUID(str(action.get("value", ""))))
        except ValueError:
            return
        payload = {
            "decision": match.group(1),
            "slack_user_id": user["id"],
            "slack_user_name": str(user.get("username") or user.get("name") or ""),
            "channel_id": channel,
            "message_ts": str((body.get("message") or {}).get("ts", "")),
        }
        await asyncio.to_thread(_forward, request_id, payload)

    ctx.register_slack_action_handler(ACTIONS, on_click)
