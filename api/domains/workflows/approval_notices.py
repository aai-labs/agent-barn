"""Send approval requests: a Slack direct message that a step's command waits for a decision.

The message only tells and links; the decision is made on the web page it links to, which
needs a signed-in session and checks the person's access there. It never contains the
command. Agent Barn posts and updates it from the outbox, so a slow or failing Slack never
delays the step or a decision, and a message stays current after the step's session stopped.
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.slack_messaging import SlackMessaging
from api.domains.events.catalog import WORKFLOW_APPROVAL_NOTICE_HANDLER, WORKFLOW_RUN_CHANGED
from api.domains.events.handlers import EventDeliveryContext, RetryableEventHandlerError, SupportedEvent
from api.domains.events.models import DomainEventEnvelope
from api.domains.workflows.approval_notice_repository import (
    ApprovalNoticeView,
    WorkflowApprovalNoticeRepository,
    shown_state,
)
from api.infrastructure.slack.client import SlackApiError

logger = logging.getLogger(__name__)

# Slack refusals worth another try; any other refusal will not change by retrying.
TRANSIENT_SLACK_ERRORS = frozenset(
    {"ratelimited", "internal_error", "fatal_error", "service_unavailable", "request_timeout"}
)
DECIDABLE = frozenset({"LIVE", "PARKED"})
# Each pass re-reads the notices; a decision landing while a message posts is caught on the next.
MAX_PASSES = 3


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def review_url(config: Config, view: ApprovalNoticeView) -> str:
    """The run on the Workflows page: a plain link that needs a signed-in session and carries no token."""
    return f"{config.web_app_url.rstrip('/')}/dashboard/{view.organization_id}/workflows?workflowRun={view.run_id}"


def card(view: ApprovalNoticeView, state: str, url: str, now: datetime) -> tuple[str, list[dict[str, Any]]]:
    """The message for a request state: a title, the time left while it waits, and the review link."""
    workflow, agent = _escape(view.workflow_name), _escape(view.agent_name)
    where = f"*{agent}* wants to run a command in step {view.step_number} of *{workflow}*."
    if state == "LIVE":
        minutes = max(1, math.ceil((view.live_until - now).total_seconds() / 60))
        epoch = int(view.live_until.timestamp())
        fallback = view.live_until.astimezone(UTC).strftime("%H:%M UTC")
        status = (
            f"About {minutes} minute{'s' if minutes != 1 else ''} left, until "
            f"<!date^{epoch}^{{time}}|{fallback}>. After that the step pauses and waits for your decision."
        )
        title, text = "Approval needed", f"Approval needed: {view.agent_name} wants to run a command"
    elif state == "PARKED":
        status = "The step is paused, waiting for your decision. It stays paused until someone decides."
        title, text = "Approval needed · step paused", f"{view.agent_name} is paused, waiting for your decision"
    else:
        title, status = {
            "APPROVED": ("Approved", "The command was approved. Nothing more is needed from you."),
            "DECLINED": ("Declined", "The command was declined. Nothing more is needed from you."),
            "LAPSED": ("Closed without a decision", "The run stopped or moved on; this request no longer waits."),
        }.get(state, ("No longer waiting", "This request no longer waits for a decision."))
        text = f"{title}: the command {view.agent_name} asked to run in {view.workflow_name}"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": False}},
        {"type": "section", "text": {"type": "mrkdwn", "text": where}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status}]},
    ]
    if state in DECIDABLE:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "review_approval",
                        "text": {"type": "plain_text", "text": "Review and approve"},
                        "url": url,
                        "style": "primary",
                    }
                ],
            }
        )
    return text, blocks


@inject
@singleton
@dataclass
class ApprovalNoticeSender:
    repository: WorkflowApprovalNoticeRepository
    slack: SlackMessaging
    config: Config

    def send(self, run_id: UUID) -> None:
        """Posts new notices of the run and brings sent ones up to date with their requests."""
        retry = False
        for _ in range(MAX_PASSES):
            due = self.repository.due(run_id)
            if not due:
                break
            for notice_id in due:
                try:
                    self.repository.under_lock(notice_id, self._deliver)
                except _SlackUnavailable:
                    retry = True
            if retry:
                break
        if retry:
            raise RetryableEventHandlerError("Slack could not be reached for an approval notice")

    def _deliver(self, view: ApprovalNoticeView) -> dict[str, Any] | None:
        state = shown_state(view.request_state)
        if view.state == "PENDING":
            return self._post(view, state)
        if view.state == "SENT" and view.shown_state != state:
            return self._update(view, state)
        return None

    def _post(self, view: ApprovalNoticeView, state: str) -> dict[str, Any]:
        if state not in DECIDABLE:
            # Decided before Slack was told: nothing is posted about a request that no longer waits.
            return {"state": "SKIPPED", "outcome": "settled_before_sent"}
        connection = self.slack.enabled_connection(view.agent_id)
        if connection is None:
            return {"state": "SKIPPED", "outcome": "no_slack_connection"}
        try:
            workspace = self.slack.workspace(connection)
        except SlackApiError as exc:
            return self._refused(exc, {"state": "FAILED"})
        except Exception as exc:
            raise _SlackUnavailable from exc
        if workspace.team_id != view.slack_team_id:
            return {"state": "SKIPPED", "outcome": "other_workspace"}
        now = datetime.now(UTC)
        text, blocks = card(view, state, review_url(self.config, view), now)
        try:
            channel_id, ts = self.slack.post_direct_message(connection, view.slack_user_id, text, blocks)
        except SlackApiError as exc:
            return self._refused(exc, {"state": "FAILED"})
        except Exception as exc:
            raise _SlackUnavailable from exc
        return {
            "state": "SENT",
            "shown_state": state,
            "connection_id": connection.id,
            "channel_id": channel_id,
            "message_ts": ts,
            "outcome": None,
        }

    def _update(self, view: ApprovalNoticeView, state: str) -> dict[str, Any]:
        connection = self.slack.connection(view.connection_id) if view.connection_id else None
        if connection is None or not view.channel_id or not view.message_ts:
            # The bot that posted it is gone; the message can no longer change.
            return {"shown_state": state, "outcome": "connection_removed"}
        text, blocks = card(view, state, review_url(self.config, view), datetime.now(UTC))
        try:
            self.slack.update_message(connection, view.channel_id, view.message_ts, text, blocks)
        except SlackApiError as exc:
            return self._refused(exc, {"shown_state": state})
        except Exception as exc:
            raise _SlackUnavailable from exc
        return {"shown_state": state}

    @staticmethod
    def _refused(exc: SlackApiError, change: dict[str, Any]) -> dict[str, Any]:
        if exc.code in TRANSIENT_SLACK_ERRORS:
            raise _SlackUnavailable from exc
        logger.warning("Slack refused an approval notice: %s", exc.code)
        return {**change, "outcome": exc.code[:100]}


class _SlackUnavailable(Exception):
    """Slack did not answer; the notice is left as it was and the delivery retried."""


@inject
@singleton
@dataclass
class ApprovalNoticeHandler:
    sender: ApprovalNoticeSender
    name: ClassVar[str] = WORKFLOW_APPROVAL_NOTICE_HANDLER
    supported_events: ClassVar[tuple[SupportedEvent, ...]] = (SupportedEvent(WORKFLOW_RUN_CHANGED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        # A delivery of its own: retrying it never touches the run or its controller.
        self.sender.send(UUID(str(event.payload["run_id"])))
