import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column, Enum, Field as SqlField, Index

from api.infrastructure.postgres.models import BaseModel


class AgentStatus(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class AgentTemplate(BaseModel, table=True):
    __tablename__: str = "agent_template"

    __table_args__ = (sa.Index("ix_agent_template_organization_id", "organization_id"),)

    organization_id: UUID = SqlField(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    version: int = SqlField(nullable=False)
    soul_md: str = SqlField(nullable=False)
    identity_md: str = SqlField(nullable=False)
    user_md: str = SqlField(nullable=False)
    tools_md: str = SqlField(nullable=False)
    agents_md: str = SqlField(nullable=False)
    boot_md: str = SqlField(nullable=False)
    bootstrap_md: str = SqlField(nullable=False)
    heartbeat_md: str = SqlField(nullable=False)


class Agent(BaseModel, table=True):
    __tablename__: str = "agent"

    __table_args__ = (
        Index("ix_agent_organization_deleted", "organization_id", "deleted_at"),
        sa.Index("ix_agent_status", "status"),
    )

    organization_id: UUID = SqlField(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    name: str = SqlField(nullable=False, max_length=255)
    slack_bot_token_encrypted: str = SqlField(nullable=False)
    slack_app_token_encrypted: str = SqlField(nullable=False)
    litellm_key_encrypted: str = SqlField(nullable=False, default="")
    status: AgentStatus = SqlField(
        default=AgentStatus.STOPPED,
        sa_column=Column(Enum(AgentStatus), nullable=False, server_default="STOPPED"),
    )
    deleted_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    template_id: UUID = SqlField(
        foreign_key="agent_template.id", nullable=False, ondelete="RESTRICT"
    )
    template_version: int = SqlField(nullable=False)


class AgentCreate(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=255)
    slack_bot_token: str = Field(min_length=1)
    slack_app_token: str = Field(min_length=1)
    soul_md: str = Field(min_length=1)
    identity_md: str = Field(min_length=1)
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None


class AgentUpdate(PydanticBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slack_bot_token: str | None = Field(default=None, min_length=1)
    slack_app_token: str | None = Field(default=None, min_length=1)
    soul_md: str | None = None
    identity_md: str | None = None
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None


class AgentRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: AgentStatus
    organization_id: UUID
    template_id: UUID
    template_version: int
    created_at: datetime
    updated_at: datetime


class AgentFilter(PydanticBaseModel):
    status: AgentStatus | None = None


def get_agent_filter(
    status: AgentStatus | None = Query(default=None),
) -> AgentFilter:
    return AgentFilter(status=status)
