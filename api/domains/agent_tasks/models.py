import enum
from datetime import datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, StringConstraints
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class AgentTaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class AgentTaskOrigin(str, enum.Enum):
    """Who recorded a Task: the Agent itself, or its runtime's Task plugin when the Agent did not."""

    AGENT = "agent"
    AUTOMATIC = "automatic"


class AgentTask(BaseModel, table=True):
    """One piece of work an Agent records for itself.

    The composite foreign key keeps a Task inside its Agent's Organization. Agent
    deletion is a soft delete, so the cascade only covers hard deletes; the Agent
    deletion transaction removes Tasks explicitly.
    """

    __tablename__: str = "agent_task"

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_task_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_task_id_organization"),
        sa.Index("ix_agent_task_organization_agent_created", "organization_id", "agent_id", "created_at"),
        sa.Index("ix_agent_task_organization_status", "organization_id", "status"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    title: str = SqlField(sa_column=Column(sa.String(length=500), nullable=False))
    description: str | None = SqlField(default=None, sa_column=Column(sa.Text(), nullable=True))
    status: AgentTaskStatus = SqlField(
        default=AgentTaskStatus.OPEN,
        sa_column=Column(
            sa.Enum(
                AgentTaskStatus,
                name="agenttaskstatus",
                values_callable=lambda statuses: [status.value for status in statuses],
            ),
            nullable=False,
        ),
    )
    origin: AgentTaskOrigin = SqlField(
        default=AgentTaskOrigin.AGENT,
        sa_column=Column(
            sa.Enum(
                AgentTaskOrigin,
                name="agenttaskorigin",
                values_callable=lambda origins: [origin.value for origin in origins],
            ),
            nullable=False,
            server_default=AgentTaskOrigin.AGENT.value,
        ),
    )


class AgentTaskNote(BaseModel, table=True):
    """An append-only entry on a Task's timeline."""

    __tablename__: str = "agent_task_note"

    __table_args__ = (sa.Index("ix_agent_task_note_task_created", "task_id", "created_at"),)

    task_id: UUID = SqlField(foreign_key="agent_task.id", nullable=False, ondelete="CASCADE")
    body: str = SqlField(sa_column=Column(sa.Text(), nullable=False))


class AgentTaskFile(BaseModel, table=True):
    """An Artifact the Agent attached to a Task; the bytes stay in Artifact storage.

    Name, type and size are copied from the Artifact when it is attached. Artifacts
    never change once published, so the copies cannot drift. Each File pins its
    Artifact, with the File's id as the pin's owner, so the Artifact does not expire
    while the Task has it.
    """

    __tablename__: str = "agent_task_file"

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["task_id", "organization_id"],
            ["agent_task.id", "agent_task.organization_id"],
            name="fk_agent_task_file_task_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("task_id", "artifact_id", name="uq_agent_task_file_task_artifact"),
        sa.Index("ix_agent_task_file_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    task_id: UUID = SqlField(nullable=False)
    artifact_id: UUID = SqlField(foreign_key="artifact.id", nullable=False, index=True)
    filename: str = SqlField(sa_column=Column(sa.String(length=255), nullable=False))
    content_type: str = SqlField(sa_column=Column(sa.String(length=128), nullable=False))
    size_bytes: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class AgentTaskCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: LongText | None = None
    # Set on create so a Task the Agent is starting on is in progress from the one request.
    status: AgentTaskStatus = AgentTaskStatus.OPEN
    origin: AgentTaskOrigin = AgentTaskOrigin.AGENT


class AgentTaskStatusUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentTaskStatus


class AgentTaskNoteCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    body: LongText


class AgentTaskFileCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID


class AgentTaskFilter(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    status: AgentTaskStatus | None = None


class AgentTaskRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    title: str
    description: str | None
    status: AgentTaskStatus
    origin: AgentTaskOrigin
    created_at: datetime
    updated_at: datetime


class AgentTaskSummary(AgentTaskRead):
    """A Task as people see it in a list: enough to tell what it produced without opening it."""

    file_count: int
    note_count: int
    # The start of the latest Note, as a preview.
    latest_note: str | None


class AgentTaskNoteRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str
    created_at: datetime


class AgentTaskFileRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class AgentTaskDetail(AgentTaskRead):
    notes: list[AgentTaskNoteRead]
    files: list[AgentTaskFileRead]
