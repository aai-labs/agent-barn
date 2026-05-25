import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Column, Enum, Field as SqlField, Index

from api.infrastructure.postgres.models import BaseModel


class AgentStatus(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class AgentPlatform(str, enum.Enum):
    SLACK = "slack"
    TEAMS = "teams"


class SlackGroupPolicy(str, enum.Enum):
    OPEN = "open"
    ALLOWLIST = "allowlist"


class SlackDmPolicy(str, enum.Enum):
    OFF = "off"
    OPEN = "open"
    ALLOWLIST = "allowlist"
    PAIRING = "pairing"


class AgentTemplate(BaseModel, table=True):
    __tablename__: str = "agent_template"

    __table_args__ = (
        sa.Index("ix_agent_template_organization_id", "organization_id"),
        sa.Index("ix_agent_template_agent_version", "agent_id", "version"),
    )

    organization_id: UUID = SqlField(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    agent_id: UUID | None = SqlField(
        default=None, foreign_key="agent.id", nullable=True
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
    model: str = SqlField(nullable=False, default="")
    platform: AgentPlatform = SqlField(
        default=AgentPlatform.SLACK,
        sa_column=Column(sa.String(10), nullable=False, server_default="slack"),
    )


class AgentSlackConfig(BaseModel, table=True):
    __tablename__: str = "agent_slack_config"

    agent_id: UUID = SqlField(
        foreign_key="agent.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    bot_token_encrypted: str = SqlField(nullable=False)
    app_token_encrypted: str = SqlField(nullable=False)
    channel_ids: list[str] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    dm_user_ids: list[str] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    group_policy: SlackGroupPolicy = SqlField(
        default=SlackGroupPolicy.ALLOWLIST,
        sa_column=Column(sa.String(), nullable=False, server_default="allowlist"),
    )
    dm_policy: SlackDmPolicy = SqlField(
        default=SlackDmPolicy.OFF,
        sa_column=Column(sa.String(), nullable=False, server_default="off"),
    )


class AgentTeamsConfig(BaseModel, table=True):
    __tablename__: str = "agent_teams_config"

    agent_id: UUID = SqlField(
        foreign_key="agent.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    app_id_encrypted: str = SqlField(nullable=False)
    app_password_encrypted: str = SqlField(nullable=False)
    tenant_id: str = SqlField(nullable=False, max_length=255)


class AgentCreate(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=255)
    platform: AgentPlatform = AgentPlatform.SLACK
    # Slack credentials (required when platform=slack)
    slack_bot_token: str | None = Field(default=None, min_length=1)
    slack_app_token: str | None = Field(default=None, min_length=1)
    slack_channel_ids: list[str] = Field(default_factory=list)
    slack_dm_user_ids: list[str] = Field(default_factory=list)
    slack_group_policy: SlackGroupPolicy = SlackGroupPolicy.ALLOWLIST
    slack_dm_policy: SlackDmPolicy = SlackDmPolicy.OFF
    # Teams credentials (required when platform=teams)
    teams_app_id: str | None = Field(default=None, min_length=1)
    teams_app_password: str | None = Field(default=None, min_length=1)
    teams_tenant_id: str | None = Field(default=None, min_length=1)
    # Template
    soul_md: str = Field(min_length=1)
    identity_md: str = Field(min_length=1)
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None
    model: str | None = None

    @model_validator(mode="after")
    def validate_platform_credentials(self) -> "AgentCreate":
        if self.platform == AgentPlatform.SLACK:
            if not self.slack_bot_token or not self.slack_app_token:
                raise ValueError(
                    "slack_bot_token and slack_app_token are required for Slack agents"
                )
        elif self.platform == AgentPlatform.TEAMS:
            if (
                not self.teams_app_id
                or not self.teams_app_password
                or not self.teams_tenant_id
            ):
                raise ValueError(
                    "teams_app_id, teams_app_password, and teams_tenant_id "
                    "are required for Teams agents"
                )
        return self


class AgentUpdate(PydanticBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Slack
    slack_bot_token: str | None = Field(default=None, min_length=1)
    slack_app_token: str | None = Field(default=None, min_length=1)
    slack_channel_ids: list[str] | None = None
    slack_dm_user_ids: list[str] | None = None
    slack_group_policy: SlackGroupPolicy | None = None
    slack_dm_policy: SlackDmPolicy | None = None
    # Teams
    teams_app_id: str | None = Field(default=None, min_length=1)
    teams_app_password: str | None = Field(default=None, min_length=1)
    teams_tenant_id: str | None = Field(default=None, min_length=1)
    # Template
    soul_md: str | None = None
    identity_md: str | None = None
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None
    model: str | None = None


class AgentSlackConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_ids: list[str]
    dm_user_ids: list[str]
    group_policy: SlackGroupPolicy
    dm_policy: SlackDmPolicy


class AgentTeamsConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str


class AgentRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: AgentStatus
    platform: AgentPlatform
    organization_id: UUID
    template_id: UUID
    template_version: int
    model: str
    slack_config: AgentSlackConfigRead | None = None
    teams_config: AgentTeamsConfigRead | None = None
    webhook_url: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentTemplateRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    version: int
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str
    created_at: datetime
    updated_at: datetime


class PairRequest(PydanticBaseModel):
    platform: str = Field(min_length=1)
    code: str = Field(min_length=1)


class AgentFilter(PydanticBaseModel):
    status: AgentStatus | None = None


class AgentHealthRead(PydanticBaseModel):
    status: str
    reason: str | None = None


def get_agent_filter(
    status: AgentStatus | None = Query(default=None),
) -> AgentFilter:
    return AgentFilter(status=status)
