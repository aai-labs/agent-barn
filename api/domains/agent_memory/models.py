from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class AgentMemoryGrant(BaseModel, table=True):
    """Grants an Agent read access, or Organization Memory read and write access.

    `agent_id` is the receiving Agent. A NULL `source_agent_id` grants Organization
    Memory, with read-only or read and write access; otherwise the grant lets the reader
    recall that one source Agent's private memories. Grants are directional; granting
    or revoking access never rewrites stored memories.
    """

    __tablename__: str = "agent_memory_grant"

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_memory_grant_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_memory_grant_source_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_agent_id IS NULL OR source_agent_id <> agent_id",
            name="ck_agent_memory_grant_not_self",
        ),
        sa.CheckConstraint(
            "access IN ('read', 'read_write') AND (source_agent_id IS NULL OR access = 'read')",
            name="ck_agent_memory_grant_access",
        ),
        sa.Index(
            "uq_agent_memory_grant_organization_memory",
            "agent_id",
            unique=True,
            postgresql_where=sa.text("source_agent_id IS NULL"),
        ),
        sa.Index(
            "uq_agent_memory_grant_agent_source",
            "agent_id",
            "source_agent_id",
            unique=True,
            postgresql_where=sa.text("source_agent_id IS NOT NULL"),
        ),
        sa.Index("ix_agent_memory_grant_organization", "organization_id"),
        sa.Index("ix_agent_memory_grant_source_agent", "source_agent_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    source_agent_id: UUID | None = SqlField(default=None, nullable=True)
    access: Literal["read", "read_write"] = SqlField(
        default="read", sa_column=Column(sa.String(), nullable=False, server_default="read")
    )
    created_by_user_id: UUID | None = SqlField(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="SET NULL",
    )


class AgentMemoryUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class AgentMemoryRead(PydanticBaseModel):
    agent_id: UUID
    enabled: bool


class AgentMemoryGrantCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    # Omitted or null grants Organization Memory.
    source_agent_id: UUID | None = None
    access: Literal["read", "read_write"] = "read"


class AgentMemoryGrantRead(PydanticBaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    source_agent_id: UUID | None
    # None for an Organization Memory grant.
    source_agent_name: str | None
    access: Literal["read", "read_write"]
    created_at: datetime


class AgentMemoryItemRead(PydanticBaseModel):
    """One memory the Agent itself wrote; `shared` marks Organization Memory it wrote."""

    id: str
    type: Literal["world", "experience", "observation"]
    text: str
    mentioned_at: datetime | None
    shared: bool


class AgentMemoryPurge(BaseModel, table=True):
    """Durable deletion tombstone; no FK so cleanup survives Organization deletion."""

    __tablename__: str = "agent_memory_purge"
    __table_args__ = (sa.Index("ix_agent_memory_purge_due", "next_attempt_at"),)
    agent_id: UUID = SqlField(nullable=False, unique=True)
    organization_id: UUID = SqlField(nullable=False)
    next_attempt_at: datetime = SqlField(
        default_factory=lambda: datetime.now(UTC), sa_column=Column(sa.DateTime(timezone=True), nullable=False)
    )
    lease_until: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True)))
    lease_id: UUID | None = SqlField(default=None)
    attempts: int = SqlField(default=0, nullable=False)
    last_cleaned_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True)))
    last_error: str | None = SqlField(default=None, max_length=32)
