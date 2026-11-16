"""Workflow approval DM cards in Slack, used by the trigger server on Hermes Agents (AF-393).

The trigger server posts a card when a step raises a live approval, relays clicks that the
agentbarn-workflow-approvals Hermes plugin forwards from it, and settles the card when the
request ends. Every Slack call here is best effort: nothing in this module may raise into the
step, which keeps waiting on, releasing or denying the command exactly as for web review.
"""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)
# Cards by request ID. Process-local: a restart ends every live step, and a parked request
# is decided on the web.
_CARDS_LOCK = threading.Lock()
_CARDS: dict[str, dict] = {}
_COMMAND_LIMIT = 2_800


class SlackError(RuntimeError):
    pass


def slack_api(method: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ.get('SLACK_BOT_TOKEN', '')}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        decoded = json.loads(response.read())
    if not isinstance(decoded, dict) or not decoded.get("ok"):
        error = decoded.get("error") if isinstance(decoded, dict) else None
        raise SlackError(f"Slack {method} failed: {error or 'unknown_error'}")
    return decoded


def card_blocks(request_id: str, command: str, note: str, review_url: str, *, buttons: bool) -> list[dict]:
    shown = command if len(command) <= _COMMAND_LIMIT else command[:_COMMAND_LIMIT] + "…"
    # Slack mrkdwn needs &, < and > escaped, and a literal fence would end the code block early.
    shown = shown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("```", "`\u200b``")
    actions: list[dict] = []
    if buttons:
        for action, label, style in (("approve", "Approve once", "primary"), ("decline", "Decline", "danger")):
            actions.append(
                {
                    "type": "button",
                    "action_id": f"agentbarn_workflow_approval_{action}",
                    "text": {"type": "plain_text", "text": label},
                    "style": style,
                    "value": request_id,
                }
            )
    if review_url:
        actions.append(
            {
                "type": "button",
                "action_id": "agentbarn_workflow_approval_open",
                "text": {"type": "plain_text", "text": "Open run"},
                "url": review_url,
            }
        )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*A workflow step wants to run this command*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```{shown}```"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]},
    ]
    if actions:
        blocks.append({"type": "actions", "elements": actions})
    return blocks


def post(request_id: str, command: str, review_url: str, live_seconds: float, callback: tuple[str, str]) -> None:
    """DM the Agent's Approval DM User. Never raises."""
    user = os.environ.get("AGENTBARN_SLACK_APPROVAL_USER", "").strip()
    if not user or not os.environ.get("SLACK_BOT_TOKEN"):
        return
    minutes = max(int(live_seconds // 60), 1)
    note = f"Decide within {minutes} min. After that the step pauses and waits for a decision on the web."
    try:
        channel = str(slack_api("conversations.open", {"users": user})["channel"]["id"])
        posted = slack_api(
            "chat.postMessage",
            {
                "channel": channel,
                "text": "A workflow step needs your approval to run a command",
                "blocks": card_blocks(request_id, command, note, review_url, buttons=True),
            },
        )
    except Exception as exc:  # any Slack or transport failure; web review carries on
        _LOGGER.warning("Could not send the workflow approval DM: %s", exc)
        return
    with _CARDS_LOCK:
        _CARDS[request_id] = {
            "channel": channel,
            "ts": str(posted.get("ts", "")),
            "command": command,
            "review_url": review_url,
            "callback": callback,
        }


def settle(request_id: str, note: str) -> None:
    """Replace the card's buttons with what happened. Never raises; the first settle wins."""
    with _CARDS_LOCK:
        card = _CARDS.pop(request_id, None)
    if card is None:
        return
    try:
        slack_api(
            "chat.update",
            {
                "channel": card["channel"],
                "ts": card["ts"],
                "text": note,
                "blocks": card_blocks(request_id, card["command"], note, card["review_url"], buttons=False),
            },
        )
    except Exception as exc:  # the step's outcome must not depend on Slack
        _LOGGER.warning("Could not update the workflow approval DM: %s", exc)


def settled_note(status: dict) -> str:
    state = status.get("state")
    if state in ("APPROVED", "DECLINED"):
        verdict = "Approved" if state == "APPROVED" else "Declined"
        if status.get("decided_in") == "slack":
            handle = status.get("decided_by_slack_handle")
            return f"{verdict} in Slack" + (f" by @{handle}" if handle else "")
        return f"{verdict} on the web"
    if state == "PARKED":
        return "Nobody decided in time, so the step paused. Decide on the web to continue it."
    return "This approval closed without a decision."


def relay(request_id: str, payload: dict, post_json: Callable[..., dict | None]) -> threading.Thread | None:
    """Report a click on our own card to the API; the step's poll then acts on the recorded decision.

    Returns the reporting thread, or None when the click is not on a card this process is waiting on.
    """
    with _CARDS_LOCK:
        card = dict(_CARDS.get(request_id) or {})
    if not card or payload.get("channel_id") != card["channel"] or payload.get("message_ts") != card["ts"]:
        return None
    token, callback_url = card["callback"]
    request_url = f"{callback_url}/approvals/{request_id}"
    body = {
        "decision": payload.get("decision"),
        "slack_user_id": payload.get("slack_user_id"),
        "slack_user_name": payload.get("slack_user_name", ""),
    }

    def report() -> None:
        try:
            post_json(f"{request_url}/slack-decision", token, body)
        except urllib.error.HTTPError as exc:
            # Refused. Once the request has been decided or closed, the waiting step settles the
            # card with what actually happened; while it is still live, say why the click failed.
            try:
                detail = str(json.loads(exc.read()).get("detail") or "")
            except Exception:
                detail = ""
            try:
                live = (post_json(request_url, token, None, method="GET") or {}).get("state") == "LIVE"
            except Exception:
                live = False
            if live:
                settle(request_id, detail or "This approval can no longer be decided in Slack.")
        except Exception as exc:
            _LOGGER.warning("Could not record the Slack approval decision: %s", exc)

    thread = threading.Thread(target=report, daemon=True)
    thread.start()
    return thread
