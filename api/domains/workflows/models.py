from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class StrictDTO(DTO):
    model_config = ConfigDict(extra="forbid")


class WorkflowInput(StrictDTO):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    label: Name
    description: Text
    type: Literal["text", "number", "boolean", "file"] = "text"
    required: bool = True


def default_capabilities() -> list[Literal["reasoning", "business_action", "native_command"]]:
    return ["reasoning"]


def default_destinations() -> list[Literal["web"]]:
    return ["web"]


class WorkflowStep(StrictDTO):
    id: UUID
    name: Name
    goal: Text
    # Retain criteria on historical snapshots; new steps need only a goal.
    completion_criteria: Text | None = None
    artifact_description: Text | None = None
    required_capabilities: list[Literal["reasoning", "business_action", "native_command"]] = Field(
        default_factory=default_capabilities, min_length=1, max_length=3
    )


class WorkflowDraft(StrictDTO):
    schema_version: Literal[1] = 1
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""
    steps: list[WorkflowStep] = Field(min_length=1, max_length=50)
    inputs: list[WorkflowInput] = Field(default_factory=list, max_length=30)
    # Other destinations require notification capability, delivered in a later slice.
    review_destination: Literal["web"] = "web"

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_final_description(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "final_artifact_description"}
        return value

    @field_validator("steps")
    @classmethod
    def unique_step_ids(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        _require_unique([str(step.id) for step in steps], "Steps", "id")
        return steps

    @field_validator("inputs")
    @classmethod
    def unique_input_keys(cls, inputs: list[WorkflowInput]) -> list[WorkflowInput]:
        _require_unique([item.key for item in inputs], "Inputs", "key")
        return inputs


def _require_unique(values: list[str], noun: str, attribute: str) -> None:
    first: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        if value in first:
            raise ValueError(f"{noun} {first[value]} and {index} share the {attribute} {value!r}; each must be unique")
        first[value] = index


class WorkflowVersionCreate(StrictDTO):
    expected_revision: int = Field(ge=1)
    draft: WorkflowDraft


class WorkflowArchive(StrictDTO):
    expected_revision: int = Field(ge=1)


class Workflow(BaseModel, table=True):
    __tablename__: str = "workflow"
    __table_args__ = (sa.CheckConstraint("revision >= 1", name="ck_workflow_revision"),)
    agent_id: UUID = SqlField(foreign_key="agent.id", ondelete="CASCADE", index=True)
    revision: int = SqlField(default=1, nullable=False)
    archived_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))


class WorkflowVersion(BaseModel, table=True):
    __tablename__: str = "workflow_version"
    __table_args__ = (
        sa.UniqueConstraint("workflow_id", "number", name="uq_workflow_version_number"),
        sa.CheckConstraint("number >= 1", name="ck_workflow_version_number"),
    )
    workflow_id: UUID = SqlField(foreign_key="workflow.id", ondelete="CASCADE", index=True)
    number: int = SqlField(nullable=False)
    snapshot: dict[str, Any] = SqlField(sa_column=sa.Column(JSONB, nullable=False))
    created_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class WorkflowVersionRead(DTO):
    id: UUID
    number: int
    created_at: datetime
    created_by_user_id: UUID | None
    draft: WorkflowDraft


class WorkflowVersionSummaryRead(DTO):
    """List projection of a saved version: enough for a card, never the full snapshot."""

    id: UUID
    number: int
    created_at: datetime
    created_by_user_id: UUID | None
    name: str
    description: str
    step_count: int
    input_count: int


class WorkflowSummaryRead(DTO):
    id: UUID
    agent_id: UUID
    revision: int
    archived_at: datetime | None
    version: WorkflowVersionSummaryRead
    allowed_actions: list[Literal["save_version", "archive"]]
    execution_available: bool = False


class WorkflowRead(DTO):
    id: UUID
    agent_id: UUID
    revision: int
    archived_at: datetime | None
    version: WorkflowVersionRead
    allowed_actions: list[Literal["save_version", "archive"]]
    execution_available: bool = False


class WorkflowCapabilitiesRead(DTO):
    authoring: bool
    execution: bool = False
    review_destinations: list[Literal["web"]] = Field(default_factory=default_destinations)
