import enum
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column, SQLModel
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class AgentTaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


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


class AgentTaskNote(BaseModel, table=True):
    """An append-only entry on a Task's timeline."""

    __tablename__: str = "agent_task_note"

    __table_args__ = (sa.Index("ix_agent_task_note_task_created", "task_id", "created_at"),)

    task_id: UUID = SqlField(foreign_key="agent_task.id", nullable=False, ondelete="CASCADE")
    body: str = SqlField(sa_column=Column(sa.Text(), nullable=False))


class AgentTaskFile(BaseModel, table=True):
    """Metadata for a File attached to a Task; its bytes live behind `TaskFileStorage`.

    `organization_id` is denormalised so the per-Organization storage total is one
    indexed sum.
    """

    __tablename__: str = "agent_task_file"

    __table_args__ = (
        sa.CheckConstraint("size_bytes > 0", name="ck_agent_task_file_size_positive"),
        sa.Index("ix_agent_task_file_task", "task_id"),
        sa.Index("ix_agent_task_file_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    task_id: UUID = SqlField(foreign_key="agent_task.id", nullable=False, ondelete="CASCADE")
    filename: str = SqlField(sa_column=Column(sa.String(length=255), nullable=False))
    content_type: str = SqlField(sa_column=Column(sa.String(length=255), nullable=False))
    size_bytes: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))


class AgentTaskFileChunk(SQLModel, table=True):
    """One ordered slice of a File's bytes, owned by the Postgres `TaskFileStorage`."""

    __tablename__: str = "agent_task_file_chunk"

    file_id: UUID = SqlField(foreign_key="agent_task_file.id", primary_key=True, ondelete="CASCADE")
    sequence: int = SqlField(primary_key=True)
    data: bytes = SqlField(sa_column=Column(sa.LargeBinary(), nullable=False))
