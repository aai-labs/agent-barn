import enum
import json
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Column, Enum, Field as SqlField, Index

from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.models import BaseModel


class AgentStatus(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class AgentPlatform(str, enum.Enum):
    SLACK = "slack"
    TEAMS = "teams"


class AgentType(str, enum.Enum):
    OPENCLAW = "openclaw"
    HERMES = "hermes"


class SlackGroupPolicy(str, enum.Enum):
    OPEN = "open"
    ALLOWLIST = "allowlist"


class SlackDmPolicy(str, enum.Enum):
    OFF = "off"
    OPEN = "open"
    ALLOWLIST = "allowlist"


# --- Integration secrets ---


class SecretProvider(str, enum.Enum):
    GITHUB = "github"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    BITBUCKET = "bitbucket"
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"
    ZOHO_MAIL = "zoho_mail"
    ZOHO_CALENDAR = "zoho_calendar"


# Predefined display labels — NOT user-entered; the backend stamps these by provider.
PROVIDER_DISPLAY_NAMES: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "GitHub credential",
    SecretProvider.JIRA: "Jira credential",
    SecretProvider.CONFLUENCE: "Confluence credential",
    SecretProvider.BITBUCKET: "Bitbucket credential",
    SecretProvider.GMAIL: "Gmail credential",
    SecretProvider.GOOGLE_CALENDAR: "Google Calendar credential",
    SecretProvider.ZOHO_MAIL: "Zoho Mail credential",
    SecretProvider.ZOHO_CALENDAR: "Zoho Calendar credential",
}


class SecretContent(PydanticBaseModel):
    """Base for per-provider credential payloads, validated on read/write."""

    model_config = ConfigDict(extra="forbid")


class GithubContent(SecretContent):
    token: str
    owner: str
    repo: str
    org: str


class JiraContent(SecretContent):
    site_url: str
    email: str
    api_token: str


class ConfluenceContent(SecretContent):
    site_url: str
    email: str
    api_token: str


class BitbucketContent(SecretContent):
    workspace: str
    repo: str
    email: str
    api_token: str


class GmailContent(SecretContent):
    access_token: str
    user_id: str


class GoogleCalendarContent(SecretContent):
    access_token: str
    calendar_id: str


class ZohoMailContent(SecretContent):
    username: str
    email: str
    from_address: str
    app_password: str
    smtp_host: str = "smtp.zoho.com"
    smtp_port: int = 465
    imap_host: str = "imap.zoho.com"
    imap_port: int = 993
    mail_folder: str = "INBOX"
    sent_folder: str = "Sent"


class ZohoCalendarContent(SecretContent):
    username: str
    email: str
    app_password: str
    caldav_url: str


PROVIDER_CONTENT_MODELS: dict[SecretProvider, type[SecretContent]] = {
    SecretProvider.GITHUB: GithubContent,
    SecretProvider.JIRA: JiraContent,
    SecretProvider.CONFLUENCE: ConfluenceContent,
    SecretProvider.BITBUCKET: BitbucketContent,
    SecretProvider.GMAIL: GmailContent,
    SecretProvider.GOOGLE_CALENDAR: GoogleCalendarContent,
    SecretProvider.ZOHO_MAIL: ZohoMailContent,
    SecretProvider.ZOHO_CALENDAR: ZohoCalendarContent,
}


def validate_content(provider: SecretProvider, raw: dict) -> SecretContent:
    """Validate a raw content dict against the provider's schema (raises on bad shape)."""
    return PROVIDER_CONTENT_MODELS[provider].model_validate(raw)


def encrypt_content(content: SecretContent, key: str) -> str:
    """Serialize and Fernet-encrypt the whole content payload into a single blob."""
    return encrypt_token(json.dumps(content.model_dump()), key)


def decrypt_content(
    provider: SecretProvider, ciphertext: str, key: str
) -> SecretContent:
    """Decrypt the blob and re-validate it against the provider's schema."""
    return validate_content(provider, json.loads(decrypt_token(ciphertext, key)))


class Agent(BaseModel, table=True):
    __tablename__: str = "agent"

    __table_args__ = (
        Index("ix_agent_organization_deleted", "organization_id", "deleted_at"),
        sa.Index("ix_agent_status", "status"),
        sa.ForeignKeyConstraint(
            ["organization_id", "template_slug", "template_version"],
            [
                "agent_template.organization_id",
                "agent_template.template_slug",
                "agent_template.version",
            ],
            name="fk_agent_template_slug_version",
            ondelete="RESTRICT",
        ),
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
    template_slug: str = SqlField(nullable=False, max_length=255)
    template_version: int = SqlField(nullable=False)
    model: str = SqlField(nullable=False, default="")
    platform: AgentPlatform = SqlField(
        default=AgentPlatform.SLACK,
        sa_column=Column(sa.String(10), nullable=False, server_default="slack"),
    )
    agent_type: AgentType = SqlField(
        default=AgentType.OPENCLAW,
        sa_column=Column(sa.String(20), nullable=False, server_default="openclaw"),
    )
    last_error: str | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.Text,
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


class AgentSecret(BaseModel, table=True):
    __tablename__: str = "agent_secret"

    __table_args__ = (
        sa.UniqueConstraint(
            "agent_id", "provider", name="uq_agent_secret_agent_provider"
        ),
    )

    agent_id: UUID = SqlField(
        foreign_key="agent.id", nullable=False, ondelete="CASCADE"
    )
    provider: SecretProvider = SqlField(sa_column=Column(sa.String(), nullable=False))
    secret_name: str = SqlField(nullable=False, max_length=255)  # predefined label
    content: str = SqlField(
        sa_column=Column(sa.Text(), nullable=False)
    )  # Fernet-encrypted JSON blob


class AgentSkill(BaseModel, table=True):
    __tablename__: str = "agent_skill"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill_agent_skill"),
    )

    agent_id: UUID = SqlField(
        foreign_key="agent.id", nullable=False, ondelete="CASCADE"
    )
    skill_id: UUID = SqlField(
        foreign_key="skill.id", nullable=False, ondelete="CASCADE"
    )


class AgentTemplateSkill(BaseModel, table=True):
    __tablename__: str = "agent_template_skill"

    __table_args__ = (
        sa.UniqueConstraint("template_id", "skill_id", name="uq_agent_template_skill"),
        sa.Index("ix_agent_template_skill_template", "template_id"),
    )

    template_id: UUID = SqlField(
        foreign_key="agent_template.id", nullable=False, ondelete="CASCADE"
    )
    skill_id: UUID = SqlField(
        foreign_key="skill.id", nullable=False, ondelete="RESTRICT"
    )


class AgentSecretCreate(PydanticBaseModel):  # no secret_name — backend stamps it
    provider: SecretProvider
    content: dict

    @model_validator(mode="after")
    def validate_provider_content(self) -> "AgentSecretCreate":
        validate_content(self.provider, self.content)
        return self


class AgentCreate(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=255)
    platform: AgentPlatform = AgentPlatform.SLACK
    agent_type: AgentType = AgentType.OPENCLAW
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
    # Template reference. The agent pins to template_version if given, else to
    # the lineage's latest version.
    template_slug: str = Field(min_length=1, max_length=255)
    template_version: int | None = None
    model: str | None = None
    # Integration credentials (optional)
    secrets: list[AgentSecretCreate] = Field(default_factory=list)
    # Custom org skills to assign on creation (optional)
    skill_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_platform_credentials(self) -> "AgentCreate":
        if self.agent_type == AgentType.HERMES and self.platform == AgentPlatform.TEAMS:
            raise ValueError("Hermes agents do not support the Teams platform")
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

    @model_validator(mode="after")
    def validate_unique_secret_providers(self) -> "AgentCreate":
        providers = [s.provider for s in self.secrets]
        if len(providers) != len(set(providers)):
            raise ValueError("Duplicate secret providers are not allowed")
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
    # Template re-pin: point the agent at a different (slug, version). Both must
    # be provided together. Per-agent markdown editing is no longer supported —
    # persona changes happen by editing templates in the catalog.
    template_slug: str | None = Field(default=None, min_length=1, max_length=255)
    template_version: int | None = None
    model: str | None = None
    skill_ids: list[UUID] = Field(default_factory=list)
    removed_skill_ids: list[UUID] = Field(default_factory=list)
    # Integration credentials: upsert (add/replace) + explicit removal.
    # Providers not mentioned in either list are left untouched.
    secrets: list[AgentSecretCreate] | None = None
    removed_secret_providers: list[SecretProvider] | None = None

    @model_validator(mode="after")
    def validate_skill_operations(self) -> "AgentUpdate":
        overlap = set(self.skill_ids) & set(self.removed_skill_ids)
        if overlap:
            ids = ", ".join(str(i) for i in overlap)
            raise ValueError(f"Skill ID(s) cannot be both added and removed: {ids}")
        return self

    @model_validator(mode="after")
    def validate_template_repin(self) -> "AgentUpdate":
        if (self.template_slug is None) != (self.template_version is None):
            raise ValueError(
                "template_slug and template_version must be provided together"
            )
        return self

    @model_validator(mode="after")
    def validate_secret_operations(self) -> "AgentUpdate":
        upserts = [s.provider for s in self.secrets or []]
        if len(upserts) != len(set(upserts)):
            raise ValueError("Duplicate secret providers are not allowed")
        removed = set(self.removed_secret_providers or [])
        overlap = removed & set(upserts)
        if overlap:
            names = ", ".join(p.value for p in overlap)
            raise ValueError(f"Provider(s) cannot be both updated and removed: {names}")
        return self


class AgentSlackConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_ids: list[str]
    dm_user_ids: list[str]
    group_policy: SlackGroupPolicy
    dm_policy: SlackDmPolicy
    bot_display_name: str | None = None  # fetched live from Slack, not persisted


class AgentTeamsConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str


class AgentSecretRead(PydanticBaseModel):  # label + provider only — no secret values
    model_config = ConfigDict(from_attributes=True)

    provider: SecretProvider
    secret_name: str


class AgentAssignedSkillRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source: str
    required_providers: list[str]
    tools_pointer: str | None
    created_at: datetime
    updated_at: datetime
    required: bool = False


class AgentRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: AgentStatus
    platform: AgentPlatform
    agent_type: AgentType
    organization_id: UUID
    template_slug: str
    template_version: int
    model: str
    slack_config: AgentSlackConfigRead | None = None
    teams_config: AgentTeamsConfigRead | None = None
    secrets: list[AgentSecretRead] = Field(default_factory=list)
    skills: list[AgentAssignedSkillRead] = Field(default_factory=list)
    webhook_url: str | None = None
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
