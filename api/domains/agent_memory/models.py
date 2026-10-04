from datetime import datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class AgentMemoryGrant(BaseModel, table=True):
    """Lets one Agent recall memories it did not write.

    `agent_id` is the reading Agent. A NULL `source_agent_id` grants Organization
    Memory, which is read and written together; otherwise the grant lets the reader
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


class AgentMemoryGrantRead(PydanticBaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    source_agent_id: UUID | None
    # None for an Organization Memory grant.
    source_agent_name: str | None
    created_at: datetime


class AgentMemoryItemRead(PydanticBaseModel):
    """One memory the Agent itself wrote; `shared` marks Organization Memory it wrote."""

    id: str
    type: Literal["world", "experience", "observation"]
    text: str
    mentioned_at: datetime | None
    shared: bool
