import enum
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, StringConstraints, field_validator
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


class AgentTaskNote(BaseModel, table=True):
    """An append-only entry on a Task's timeline."""

    __tablename__: str = "agent_task_note"

    __table_args__ = (sa.Index("ix_agent_task_note_task_created", "task_id", "created_at"),)

    task_id: UUID = SqlField(foreign_key="agent_task.id", nullable=False, ondelete="CASCADE")
    body: str = SqlField(sa_column=Column(sa.Text(), nullable=False))


class AgentTaskFile(BaseModel, table=True):
    """Metadata for a File attached to a Task; its bytes live behind `TaskFileStorage`.

    `organization_id` is denormalised so the per-Organization storage total is one
    indexed sum; the composite foreign key keeps it equal to the Task's.
    """

    __tablename__: str = "agent_task_file"

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["task_id", "organization_id"],
            ["agent_task.id", "agent_task.organization_id"],
            name="fk_agent_task_file_task_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_agent_task_file_size_positive"),
        sa.Index("ix_agent_task_file_task", "task_id"),
        sa.Index("ix_agent_task_file_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    task_id: UUID = SqlField(nullable=False)
    filename: str = SqlField(sa_column=Column(sa.String(length=255), nullable=False))
    content_type: str = SqlField(sa_column=Column(sa.String(length=255), nullable=False))
    size_bytes: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))


class AgentTaskFileChunk(SQLModel, table=True):
    """One ordered slice of a File's bytes, owned by the Postgres `TaskFileStorage`.

    The foreign key is checked at commit, so chunks can be written before the File row
    that records their total size.
    """

    __tablename__: str = "agent_task_file_chunk"

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["agent_task_file.id"],
            name="fk_agent_task_file_chunk_file",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    file_id: UUID = SqlField(primary_key=True)
    sequence: int = SqlField(primary_key=True)
    data: bytes = SqlField(sa_column=Column(sa.LargeBinary(), nullable=False))


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class AgentTaskCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: LongText | None = None


class AgentTaskNoteCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    body: LongText


# Path separators, quotes, C0 and C1 control characters, and the Unicode marks that
# reorder how a name is displayed.
_UNSAFE_FILENAME_CHARACTERS = re.compile(r'[/\\"\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]')


class AgentTaskFileCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    # A bare `type/subtype`, without parameters. Serving a File safely (as an
    # attachment, never sniffed) is still the download route's job.
    content_type: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            max_length=255,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$",
        ),
    ]

    @field_validator("filename")
    @classmethod
    def _bare_name(cls, filename: str) -> str:
        """A name that is safe to write to disk and to offer back as a download name."""
        if filename in {".", ".."} or _UNSAFE_FILENAME_CHARACTERS.search(filename):
            raise ValueError("The filename must be a plain name, without paths, quotes or control characters.")
        return filename


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
    created_at: datetime
    updated_at: datetime


class AgentTaskNoteRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str
    created_at: datetime


class AgentTaskFileRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class AgentTaskDetail(AgentTaskRead):
    notes: list[AgentTaskNoteRead]
    files: list[AgentTaskFileRead]
