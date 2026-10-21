import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Enum
from sqlmodel import Field as SqlField

from api.domains.playbooks.constants import (
    DEFAULT_MAX_SESSIONS,
    DEFAULT_WINDOW_DAYS,
    MAX_SESSIONS_LIMIT,
    MAX_WINDOW_DAYS,
)
from api.infrastructure.postgres.models import BaseModel


class PlaybookExtractionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_STATUSES = (PlaybookExtractionStatus.QUEUED, PlaybookExtractionStatus.RUNNING)
ACTIVE_AGENT_INDEX = "uq_playbook_extraction_active_agent"


class PlaybookExtractionError(str, enum.Enum):
    """Why a run failed. Stored and returned instead of upstream error text."""

    ENQUEUE_FAILED = "enqueue_failed"
    REQUESTER_LOST_ACCESS = "requester_lost_access"
    SOURCE_AGENT_UNAVAILABLE = "source_agent_unavailable"
    NO_SESSIONS = "no_sessions"
    MODEL_UNAVAILABLE = "model_unavailable"
    SPEND_LIMIT_REACHED = "spend_limit_reached"
    MODEL_ERROR = "model_error"
    ANSWER_TRUNCATED = "answer_truncated"
    DRAFT_CONFLICT = "draft_conflict"
    SKILL_UNAVAILABLE = "skill_unavailable"
    INTERNAL_ERROR = "internal_error"


class PlaybookExtraction(BaseModel, table=True):
    """One run that turns a source Agent's recent work into an Organization Skill Draft.

    ``skill_id`` names the target lineage. It is set at request time when the run
    refreshes an existing playbook and at completion when the run creates one; if the
    target is deleted first, the run creates a new lineage named ``skill_name``.
    """

    __tablename__: str = "playbook_extraction"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["source_agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_playbook_extraction_source_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("window_end > window_start", name="ck_playbook_extraction_window"),
        sa.CheckConstraint(
            f"max_sessions BETWEEN 1 AND {MAX_SESSIONS_LIMIT}", name="ck_playbook_extraction_max_sessions"
        ),
        sa.Index("ix_playbook_extraction_agent_created", "source_agent_id", "created_at"),
        sa.Index("ix_playbook_extraction_skill", "skill_id"),
        # One run per source Agent at a time bounds spend and keeps the claim simple.
        sa.Index(
            ACTIVE_AGENT_INDEX,
            "source_agent_id",
            unique=True,
            postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    source_agent_id: UUID = SqlField(nullable=False)
    requested_by_membership_id: UUID | None = SqlField(
        default=None, foreign_key="user_organization.id", nullable=True, ondelete="SET NULL"
    )
    requested_by_user_id: UUID | None = SqlField(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    skill_id: UUID | None = SqlField(default=None, foreign_key="skill.id", nullable=True, ondelete="SET NULL")
    skill_name: str = SqlField(max_length=255, nullable=False)
    window_start: datetime = SqlField(sa_column=Column(sa.DateTime(timezone=True), nullable=False))
    window_end: datetime = SqlField(sa_column=Column(sa.DateTime(timezone=True), nullable=False))
    max_sessions: int = SqlField(nullable=False)
    status: PlaybookExtractionStatus = SqlField(
        default=PlaybookExtractionStatus.QUEUED,
        sa_column=Column(Enum(PlaybookExtractionStatus), nullable=False, server_default="QUEUED"),
    )
    model: str | None = SqlField(default=None, max_length=200, nullable=True)
    prompt_version: str | None = SqlField(default=None, max_length=40, nullable=True)
    session_keys: list[str] = SqlField(default_factory=list, sa_column=Column(JSONB, nullable=False))
    session_count: int = SqlField(default=0, nullable=False)
    message_count: int = SqlField(default=0, nullable=False)
    tool_call_count: int = SqlField(default=0, nullable=False)
    memory_count: int = SqlField(default=0, nullable=False)
    input_chars: int = SqlField(default=0, nullable=False)
    prompt_tokens: int = SqlField(default=0, nullable=False)
    completion_tokens: int = SqlField(default=0, nullable=False)
    cost_usd: Decimal | None = SqlField(default=None, sa_column=Column(sa.Numeric(20, 12), nullable=True))
    result_markdown: str | None = SqlField(default=None, sa_column=Column(sa.Text, nullable=True))
    # Proposed Organization Conventions: [{"rule": str, "conversations": int}], reviewed before use.
    result_conventions: list[dict[str, Any]] = SqlField(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    # A plain string column: new codes ship without a database enum migration.
    error_code: str | None = SqlField(default=None, sa_column=Column(sa.String(64), nullable=True))
    started_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))
    finished_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))


class PlaybookExtractionCreate(PydanticBaseModel):
    """Start a run that writes either a new playbook or the next draft of an existing one."""

    model_config = ConfigDict(extra="forbid")

    skill_id: UUID | None = None
    skill_name: str | None = Field(default=None, min_length=1, max_length=255)
    window_days: int = Field(default=DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS)
    max_sessions: int = Field(default=DEFAULT_MAX_SESSIONS, ge=1, le=MAX_SESSIONS_LIMIT)

    @model_validator(mode="after")
    def one_target(self) -> Self:
        if (self.skill_id is None) == (self.skill_name is None or not self.skill_name.strip()):
            raise ValueError("Provide either skill_id for an existing playbook or skill_name for a new one")
        if self.skill_name is not None:
            self.skill_name = self.skill_name.strip()
        return self


class PlaybookExtractionRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    source_agent_id: UUID
    source_agent_name: str
    skill_id: UUID | None
    skill_name: str
    status: PlaybookExtractionStatus
    error_code: PlaybookExtractionError | None
    window_start: datetime
    window_end: datetime
    max_sessions: int
    model: str | None
    session_count: int
    message_count: int
    tool_call_count: int
    memory_count: int
    input_chars: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal | None
    requested_by_user_id: UUID | None
    convention_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: PlaybookExtraction, source_agent_name: str) -> Self:
        return cls.model_validate(
            {
                **row.model_dump(),
                "source_agent_name": source_agent_name,
                "convention_count": len(row.result_conventions or []),
                "conventions": row.result_conventions or [],
            }
        )


class PlaybookConventionRead(PydanticBaseModel):
    rule: str
    conversations: int


class PlaybookExtractionDetailRead(PlaybookExtractionRead):
    """Adds the generated playbook, kept so a run whose draft could not be written loses nothing,
    and the Organization Conventions it proposed."""

    result_markdown: str | None
    conventions: list[PlaybookConventionRead]


class PlaybookExtractionPreview(PydanticBaseModel):
    """What a run with these settings would read now, before anything is billed."""

    window_start: datetime
    window_end: datetime
    session_count: int
    message_count: int
    tool_call_count: int
    input_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    model: str


class PlaybookExtractionFilter(PydanticBaseModel):
    skill_id: UUID | None = None
