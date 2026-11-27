"""Durable WF02 execution records. Each attempt runs as a new session in the Agent chosen for the run,
except one continuing a late approval decision, which resumes its step's session."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SqlField

from api.domains.workflows.models import Name, StrictDTO, Text
from api.infrastructure.postgres.models import BaseModel

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "REJECTED"})
RunState = Literal[
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "BLOCKED",
    "AWAITING_APPROVAL",
    "CANCELLING",
    "CANCELLED",
    "SUCCEEDED",
    "FAILED",
    "REJECTED",
]
RUN_STATE_CHECK = (
    "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','AWAITING_APPROVAL','CANCELLING','CANCELLED',"
    "'SUCCEEDED','FAILED','REJECTED')"
)
# A live request is answered while the step's session holds it; a parked one after the session stopped.
ApprovalState = Literal["LIVE", "PARKED", "APPROVED", "DECLINED", "RELEASED", "LAPSED"]
DECIDABLE_APPROVAL_STATES = frozenset({"LIVE", "PARKED"})
# A round at an Approval step waits for a person; each Request changes opens the next round.
StepApprovalState = Literal["WAITING", "APPROVED", "CHANGES_REQUESTED", "REJECTED", "LAPSED"]


class WorkflowFileInput(StrictDTO):
    artifact_id: UUID
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")


InputValue = StrictStr | StrictInt | StrictFloat | StrictBool | WorkflowFileInput


class WorkflowRunCreate(StrictDTO):
    workflow_id: UUID
    # The Agent that runs every step of this run.
    agent_id: UUID
    version_id: UUID
    title: Name | None = None
    client_request_id: UUID
    inputs: dict[str, InputValue] = Field(default_factory=dict, max_length=30)


class WorkflowRunRerun(StrictDTO):
    """A re-run takes its version and inputs from the original run, never from the caller."""

    client_request_id: UUID


class WorkflowRunCancel(StrictDTO):
    expected_revision: int = Field(ge=1)


class WorkflowRun(BaseModel, table=True):
    __tablename__: str = "workflow_run"
    __table_args__ = (
        sa.UniqueConstraint("workflow_id", "client_request_id", name="uq_workflow_run_start"),
        sa.CheckConstraint("revision >= 1 AND next_step >= 0 AND generation >= 0", name="ck_workflow_run_counters"),
        sa.CheckConstraint(RUN_STATE_CHECK, name="ck_workflow_run_state"),
    )
    workflow_id: UUID = SqlField(foreign_key="workflow.id", ondelete="CASCADE", index=True)
    agent_id: UUID = SqlField(foreign_key="agent.id", ondelete="CASCADE", index=True)
    version_id: UUID = SqlField(foreign_key="workflow_version.id", ondelete="CASCADE")
    title: str | None = None
    initiating_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    initiating_membership_id: UUID | None = SqlField(
        default=None, foreign_key="user_organization.id", ondelete="SET NULL"
    )
    client_request_id: UUID
    request_hash: str
    inputs: dict[str, Any] = SqlField(sa_column=sa.Column(JSONB, nullable=False))
    state: str = "QUEUED"
    revision: int = 1
    next_step: int = 0
    generation: int = 0
    runtime: str
    reason: str | None = None
    settled_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    content_expired: bool = False
    # Set when this run repeats another run's version and inputs.
    rerun_of_run_id: UUID | None = SqlField(
        default=None, foreign_key="workflow_run.id", ondelete="SET NULL", index=True
    )


class WorkflowAttempt(BaseModel, table=True):
    __tablename__: str = "workflow_attempt"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "generation", name="uq_workflow_attempt_generation"),
        sa.CheckConstraint("generation >= 1 AND step_index >= 0", name="ck_workflow_attempt_counters"),
        sa.CheckConstraint(
            "state IN ('REASONING','STOPPING','STOPPED','COMPLETED','FAILED')", name="ck_workflow_attempt_state"
        ),
    )
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    generation: int
    step_index: int
    state: str = "REASONING"
    capability_hash: str
    expires_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    # Set once the Agent accepted the step; a step is never sent to the Agent twice.
    dispatched_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    result_hash: str | None = None


class WorkflowCheckpoint(BaseModel, table=True):
    __tablename__: str = "workflow_checkpoint"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "step_index", "round", name="uq_workflow_checkpoint_round"),
        sa.CheckConstraint("round >= 1", name="ck_workflow_checkpoint_round"),
    )
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    attempt_id: UUID = SqlField(foreign_key="workflow_attempt.id", ondelete="CASCADE")
    step_index: int
    # A step runs again only when a person requests changes at the Approval step after it.
    round: int = 1
    # Set when changes were requested; later steps and the run's result use only the current round.
    superseded_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    result: dict[str, Any] = SqlField(sa_column=sa.Column(JSONB, nullable=False))


class WorkflowStepApproval(BaseModel, table=True):
    """One round at an Approval step: a person approves the step before it, requests changes or rejects."""

    __tablename__: str = "workflow_step_approval"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "step_index", "round", name="uq_workflow_step_approval_round"),
        sa.CheckConstraint("round >= 1 AND step_index >= 1", name="ck_workflow_step_approval_counters"),
        sa.CheckConstraint(
            "state IN ('WAITING','APPROVED','CHANGES_REQUESTED','REJECTED','LAPSED')",
            name="ck_workflow_step_approval_state",
        ),
        # A run waits at one Approval step at a time; inbox and badge reads use this index.
        sa.Index(
            "uq_workflow_step_approval_waiting",
            "run_id",
            unique=True,
            postgresql_where=sa.text("state = 'WAITING'"),
        ),
    )
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    step_index: int
    round: int
    state: str = "WAITING"
    decided_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    decided_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    # Required when changes are requested; optional with an approval or a rejection.
    note: str | None = None


class WorkflowApprovalRequest(BaseModel, table=True):
    """One exact command a step's Agent asked a person to allow; each ask is a new request."""

    __tablename__: str = "workflow_approval_request"
    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('LIVE','PARKED','APPROVED','DECLINED','RELEASED','LAPSED')",
            name="ck_workflow_approval_request_state",
        ),
        # Inbox and badge reads look only for requests still awaiting a decision.
        sa.Index(
            "ix_workflow_approval_request_open",
            "run_id",
            postgresql_where=sa.text("state IN ('LIVE','PARKED')"),
        ),
    )
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    attempt_id: UUID = SqlField(foreign_key="workflow_attempt.id", ondelete="CASCADE")
    step_index: int
    # The runtime session holding the request; a late decision continues this session.
    session_id: str
    runtime_run_id: str
    command: str
    command_sha256: str
    state: str = "LIVE"
    live_until: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    decided_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    decided_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    guidance: str | None = None
    # Set when a late decision's continuation attempt picks the session back up.
    continued_by_attempt_id: UUID | None = SqlField(
        default=None, foreign_key="workflow_attempt.id", ondelete="SET NULL"
    )


class WorkflowHistory(BaseModel, table=True):
    __tablename__: str = "workflow_history"
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    revision: int
    kind: str
    detail: str


class AttemptResult(StrictDTO):
    summary: Text
    criteria_met: Literal[True]


class AttemptFailure(StrictDTO):
    reason: str = Field(min_length=1, max_length=2000)
    # The Agent stopped for something only a person can resolve, such as a command approval.
    needs_attention: bool = False
    # False for a definitive failure, such as unmet criteria; the run fails immediately.
    retryable: bool = True


class ApprovalRaised(StrictDTO):
    """The step's runtime paused a command for a person's approval."""

    command: str = Field(min_length=1, max_length=100_000)
    runtime_run_id: str = Field(min_length=1, max_length=256)
    # Seconds since the runtime raised the request; its own approval timeout runs from then.
    age_seconds: float = Field(default=0, ge=0, le=3600)


class ApprovalDecisionCreate(StrictDTO):
    decision: Literal["approve", "decline"]
    guidance: str | None = Field(default=None, max_length=4000)


class StepApprovalDecisionCreate(StrictDTO):
    decision: Literal["approve", "request_changes", "reject"]
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def changes_need_notes(self) -> StepApprovalDecisionCreate:
        self.note = (self.note or "").strip() or None
        if self.decision == "request_changes" and self.note is None:
            raise ValueError("Say what should change when requesting changes")
        return self


class StepApprovalRead(DTO):
    id: UUID
    step_index: int
    round: int
    state: StepApprovalState
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    note: str | None


class ApprovalRead(DTO):
    id: UUID
    step_index: int
    command: str
    state: ApprovalState
    created_at: datetime
    live_until: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    guidance: str | None


class WorkflowHistoryRead(DTO):
    id: UUID
    created_at: datetime
    revision: int
    kind: str
    detail: str


class AttemptRead(DTO):
    number: int
    started_at: datetime
    expires_at: datetime
    # The API's clock, so a browser with a skewed clock can still show elapsed and remaining time.
    server_time: datetime
    # The Agent has not accepted this attempt's step after the grace period.
    agent_unresponsive: bool


class WorkflowRunRead(DTO):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    version_number: int
    name: str
    # The run's own title, when the person starting it gave one.
    title: str | None = None
    agent_id: UUID
    agent_name: str
    # The Agent was deleted; the run stays readable but nothing more can be done with it.
    agent_archived: bool
    initiating_user_id: UUID | None
    inputs: dict[str, Any]
    state: RunState
    revision: int
    next_step: int
    generation: int
    steps: list[dict[str, Any]]
    reason: str | None
    # The final step's reported summary; present only once the run has succeeded.
    final_summary: str | None = None
    final_output_description: str | None = None
    final_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    settled_at: datetime | None
    rerun_of_run_id: UUID | None = None
    allowed_actions: list[Literal["cancel", "rerun", "decide", "decide_step"]]
    # The running step's current attempt; only present on the single-run read.
    attempt: AttemptRead | None = None
    # The latest approval request of the current step; on list reads only while it awaits a decision.
    approval: ApprovalRead | None = None
    # Every approval request of the run, oldest first; only present on the single-run read.
    approvals: list[ApprovalRead] = Field(default_factory=list)
    # The Approval step round awaiting a decision, if the run is waiting at one.
    step_approval: StepApprovalRead | None = None
    # Every Approval step round of the run, oldest first; only present on the single-run read.
    step_approvals: list[StepApprovalRead] = Field(default_factory=list)
