from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, or_, select

from api.domains.agents.models import Agent
from api.domains.workflows.models import WorkflowVersion
from api.domains.workflows.run_models import WorkflowApprovalNotice, WorkflowApprovalRequest, WorkflowRun
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# The approval request states a notice can show; a released request was approved.
SHOWN_STATE = {"RELEASED": "APPROVED"}


def shown_state(request_state: str) -> str:
    return SHOWN_STATE.get(request_state, request_state)


@dataclass(frozen=True)
class ApprovalNoticeView:
    """What a notice shows, read under its lock: never the command."""

    notice_id: UUID
    state: str
    shown_state: str | None
    slack_user_id: str
    slack_team_id: str
    connection_id: UUID | None
    channel_id: str | None
    message_ts: str | None
    request_state: str
    live_until: datetime
    step_number: int
    run_id: UUID
    organization_id: UUID
    agent_id: UUID
    agent_name: str
    workflow_name: str


@inject
@singleton
@dataclass
class WorkflowApprovalNoticeRepository:
    """Background work for the event worker: it is never reachable from a router, and reads only
    the persisted run, request and notice an event names."""

    delegate: PostgresRepositoryDelegate

    def due(self, run_id: UUID) -> list[UUID]:
        """Notices of the run still to be sent, or whose message shows an earlier request state."""
        with Session(self.delegate.engine) as session:
            request_shown = sa.case(
                *((col(WorkflowApprovalRequest.state) == raw, shown) for raw, shown in SHOWN_STATE.items()),
                else_=col(WorkflowApprovalRequest.state),
            )
            return list(
                session.exec(
                    select(WorkflowApprovalNotice.id)
                    .join(
                        WorkflowApprovalRequest,
                        col(WorkflowApprovalRequest.id) == col(WorkflowApprovalNotice.request_id),
                    )
                    .where(
                        col(WorkflowApprovalNotice.run_id) == run_id,
                        or_(
                            col(WorkflowApprovalNotice.state) == "PENDING",
                            sa.and_(
                                col(WorkflowApprovalNotice.state) == "SENT",
                                col(WorkflowApprovalNotice.shown_state).is_distinct_from(request_shown),
                            ),
                        ),
                    )
                    .order_by(col(WorkflowApprovalNotice.created_at))
                ).all()
            )

    def under_lock(self, notice_id: UUID, work: Callable[[ApprovalNoticeView], dict[str, Any] | None]) -> None:
        """Runs `work` on the notice's current state, one at a time per notice, and records the
        notice fields it returns.

        The lock is a transaction-level advisory lock, not a row lock, so deciding the request on
        the web never waits for Slack.
        """
        with Session(self.delegate.engine) as session:
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"workflow-approval-notice:{notice_id}"},
            )
            view = self._view(session, notice_id)
            if view is None:
                return
            change = work(view)
            if change:
                notice = session.get_one(WorkflowApprovalNotice, notice_id)
                for name, value in change.items():
                    setattr(notice, name, value)
                session.add(notice)
            session.commit()

    @staticmethod
    def _view(session: Session, notice_id: UUID) -> ApprovalNoticeView | None:
        row = session.exec(
            select(WorkflowApprovalNotice, WorkflowApprovalRequest, WorkflowRun, Agent)
            .join(WorkflowApprovalRequest, col(WorkflowApprovalRequest.id) == col(WorkflowApprovalNotice.request_id))
            .join(WorkflowRun, col(WorkflowRun.id) == col(WorkflowApprovalNotice.run_id))
            .join(Agent, col(Agent.id) == col(WorkflowRun.agent_id))
            .where(col(WorkflowApprovalNotice.id) == notice_id)
        ).one_or_none()
        if row is None:
            return None
        notice, request, run, agent = row
        version = session.get_one(WorkflowVersion, run.version_id)
        return ApprovalNoticeView(
            notice_id=notice.id,
            state=notice.state,
            shown_state=notice.shown_state,
            slack_user_id=notice.slack_user_id,
            slack_team_id=notice.slack_team_id,
            connection_id=notice.connection_id,
            channel_id=notice.channel_id,
            message_ts=notice.message_ts,
            request_state=request.state,
            live_until=request.live_until,
            step_number=request.step_index + 1,
            run_id=run.id,
            organization_id=agent.organization_id,
            agent_id=agent.id,
            agent_name=agent.name,
            workflow_name=str(version.snapshot.get("name") or "Workflow"),
        )
