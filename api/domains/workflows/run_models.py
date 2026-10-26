"""Durable WF02 execution records. Each attempt runs as a new session in the owning Agent."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SqlField

from api.domains.workflows.models import StrictDTO, Text
from api.infrastructure.postgres.models import BaseModel

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
RunState = Literal["QUEUED", "RUNNING", "PAUSED", "BLOCKED", "CANCELLING", "CANCELLED", "SUCCEEDED", "FAILED"]
InputValue = StrictStr | StrictInt | StrictFloat | StrictBool


class WorkflowRunCreate(StrictDTO):
    version_id: UUID
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
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','CANCELLING','CANCELLED','SUCCEEDED','FAILED')",
            name="ck_workflow_run_state",
        ),
    )
    workflow_id: UUID = SqlField(foreign_key="workflow.id", ondelete="CASCADE", index=True)
    version_id: UUID = SqlField(foreign_key="workflow_version.id", ondelete="CASCADE")
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
    rerun_of_run_id: UUID | None = SqlField(default=None, foreign_key="workflow_run.id", ondelete="SET NULL")


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
    __table_args__ = (sa.UniqueConstraint("run_id", "step_index", name="uq_workflow_checkpoint_step"),)
    run_id: UUID = SqlField(foreign_key="workflow_run.id", ondelete="CASCADE", index=True)
    attempt_id: UUID = SqlField(foreign_key="workflow_attempt.id", ondelete="CASCADE")
    step_index: int
    result: dict[str, Any] = SqlField(sa_column=sa.Column(JSONB, nullable=False))


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
    # False when retrying cannot help, such as unmet step criteria; the run fails immediately.
    retryable: bool = True


class WorkflowHistoryRead(DTO):
    id: UUID
    created_at: datetime
    revision: int
    kind: str
    detail: str


class AttemptRead(DTO):
    number: int
    limit: int
    started_at: datetime
    expires_at: datetime
    # The Agent has not accepted this attempt's step after the grace period.
    agent_unresponsive: bool


class WorkflowRunRead(DTO):
    id: UUID
    workflow_id: UUID
    version_id: UUID
    version_number: int
    name: str
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
    created_at: datetime
    settled_at: datetime | None
    rerun_of_run_id: UUID | None = None
    allowed_actions: list[Literal["cancel", "rerun"]]
    # The running step's current attempt; only present on the single-run read.
    attempt: AttemptRead | None = None
