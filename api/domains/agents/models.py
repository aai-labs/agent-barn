import enum
import json
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlmodel import Column, Enum, Index
from sqlmodel import Field as SqlField

from api.domains.agents.google_workspace_scopes import required_service_scopes
from api.domains.rbac.catalog import PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.models import BaseModel


class AgentStatus(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class CommandApprovalMode(str, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"
    OFF = "off"


class AgentType(str, enum.Enum):
    OPENCLAW = "openclaw"
    HERMES = "hermes"


class AgentTemplateOverrideSourceType(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"


class AgentTemplatePinType(str, enum.Enum):
    SHARED = "shared"
    OVERRIDE = "override"


# --- Integration secrets ---


class SecretProvider(str, enum.Enum):
    GITHUB = "github"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    BITBUCKET = "bitbucket"
    ZOHO_MAIL = "zoho_mail"
    ZOHO_CALENDAR = "zoho_calendar"
    FIRECRAWL = "firecrawl"
    SLACK = "slack"
    PIPEDRIVE = "pipedrive"
    GOOGLE_WORKSPACE = "google_workspace"


# Google services a google_workspace credential may cover, as named by the gog CLI.
# The OAuth scope and runtime-policy maps are checked against this allowlist in tests.
GOOGLE_WORKSPACE_SERVICES: tuple[str, ...] = ("gmail", "calendar", "drive", "sheets")


# Predefined display labels — NOT user-entered; the backend stamps these by provider.
PROVIDER_DISPLAY_NAMES: dict[SecretProvider, str] = {
    SecretProvider.GITHUB: "GitHub credential",
    SecretProvider.JIRA: "Jira credential",
    SecretProvider.CONFLUENCE: "Confluence credential",
    SecretProvider.BITBUCKET: "Bitbucket credential",
    SecretProvider.ZOHO_MAIL: "Zoho Mail credential",
    SecretProvider.ZOHO_CALENDAR: "Zoho Calendar credential",
    SecretProvider.FIRECRAWL: "Firecrawl credential",
    SecretProvider.SLACK: "Slack credential",
    SecretProvider.PIPEDRIVE: "Pipedrive credential",
    SecretProvider.GOOGLE_WORKSPACE: "Google Workspace credential",
}


class SecretContent(PydanticBaseModel):
    """Base for per-provider credential payloads, validated on read/write."""

    model_config = ConfigDict(extra="forbid")


class _RepoListCompat(SecretContent):
    """Upgrades legacy singular `repo` -> `repos: list[str]` on read, so old
    encrypted blobs (repo: "single-string") decrypt transparently."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_repo(cls, data):
        if isinstance(data, dict) and "repo" in data and "repos" not in data:
            data = dict(data)
            legacy = data.pop("repo")
            data["repos"] = [legacy] if legacy else []
        return data


class GithubContent(_RepoListCompat):
    token: str
    owner: str
    repos: list[str] = Field(default_factory=list)
    org: str


class JiraContent(SecretContent):
    site_url: str
    use_scoped_token: bool = False
    email: str
    api_token: str
    # Populated at save time for scoped tokens: the API Gateway URL (site_url
    # doesn't accept scoped tokens directly) needs the resolved cloud ID.
    cloud_id: str = ""


class ConfluenceContent(SecretContent):
    site_url: str
    use_scoped_token: bool = False
    email: str
    api_token: str
    # Populated at save time for scoped tokens: the API Gateway URL (site_url
    # doesn't accept scoped tokens directly) needs the resolved cloud ID.
    cloud_id: str = ""


class BitbucketContent(_RepoListCompat):
    workspace: str
    repos: list[str] = Field(default_factory=list)
    email: str
    api_token: str


class GoogleWorkspaceContent(SecretContent):
    """Credential for the gog CLI: one refresh token covering several Google services.

    Unlike the per-service Google providers above, one consent covers every service in
    ``services``. ``scopes`` records what Google actually granted (the token response's
    ``scope``), which is what the validator compares against on re-check — the user can
    uncheck individual scopes on the consent screen, so requested != granted.

    ``client_id``/``client_secret`` are optional: empty means the
    server-owned client is backfilled from config at agent-start time.
    """

    email: str = Field(min_length=1)
    services: list[str]
    scopes: list[str] = Field(default_factory=list)
    refresh_token: str
    read_only: bool = False
    client_id: str = ""
    client_secret: str = ""

    @field_validator("services")
    @classmethod
    def _validate_services(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one service is required")
        unknown = [s for s in value if s not in GOOGLE_WORKSPACE_SERVICES]
        if unknown:
            raise ValueError(
                f"unsupported service(s): {', '.join(unknown)}. Supported: {', '.join(GOOGLE_WORKSPACE_SERVICES)}"
            )
        # Deduplicate while keeping the caller's order so the stored list, the consent
        # scopes, and GOG_TOKEN_JSON all agree.
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_granted_scopes(self) -> Self:
        if not self.scopes:
            return self
        missing = sorted(required_service_scopes(self.services, self.read_only) - set(self.scopes))
        if missing:
            raise ValueError(
                "scopes do not cover the selected Google services at the configured access level: " + ", ".join(missing)
            )
        return self


class ZohoMailContent(SecretContent):
    email: str
    account_id: str
    client_id: str
    client_secret: str
    refresh_token: str


class ZohoCalendarContent(SecretContent):
    username: str
    email: str
    app_password: str
    caldav_url: str


class FirecrawlContent(SecretContent):
    api_key: str
    base_url: str = ""


class SlackContent(SecretContent):
    token: str


class PipedriveContent(SecretContent):
    api_token: str
    # Bare subdomain, e.g. "aai-labs" (-> https://aai-labs.pipedrive.com). Optional: a
    # Pipedrive personal API token is self-identifying, so the global
    # https://api.pipedrive.com endpoint works for any account without this.
    domain: str = ""


PROVIDER_CONTENT_MODELS: dict[SecretProvider, type[SecretContent]] = {
    SecretProvider.GITHUB: GithubContent,
    SecretProvider.JIRA: JiraContent,
    SecretProvider.CONFLUENCE: ConfluenceContent,
    SecretProvider.BITBUCKET: BitbucketContent,
    SecretProvider.ZOHO_MAIL: ZohoMailContent,
    SecretProvider.ZOHO_CALENDAR: ZohoCalendarContent,
    SecretProvider.FIRECRAWL: FirecrawlContent,
    SecretProvider.SLACK: SlackContent,
    SecretProvider.PIPEDRIVE: PipedriveContent,
    SecretProvider.GOOGLE_WORKSPACE: GoogleWorkspaceContent,
}


def validate_content(provider: SecretProvider, raw: dict) -> SecretContent:
    """Validate a raw content dict against the provider's schema (raises on bad shape)."""
    return PROVIDER_CONTENT_MODELS[provider].model_validate(raw)


def encrypt_content(content: SecretContent, key: str) -> str:
    """Serialize and Fernet-encrypt the whole content payload into a single blob."""
    return encrypt_token(json.dumps(content.model_dump()), key)


def decrypt_content(provider: SecretProvider, ciphertext: str, key: str) -> SecretContent:
    """Decrypt the blob and re-validate it against the provider's schema."""
    return validate_content(provider, json.loads(decrypt_token(ciphertext, key)))


class Agent(BaseModel, table=True):
    __tablename__: str = "agent"

    __table_args__ = (
        Index("ix_agent_organization_deleted", "organization_id", "deleted_at"),
        sa.Index("ix_agent_status", "status"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_agent_id_organization",
        ),
        # An active agent pins exactly one shared or Agent-owned template
        # version. Soft-deleted agents retain their pin for history and may be
        # detached when an old shared lineage is purged.
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR ((platform_template_id IS NOT NULL)::integer "
            "+ (agent_template_id IS NOT NULL)::integer "
            "+ (agent_template_override_version_id IS NOT NULL)::integer = 1)",
            name="ck_agent_template_pin_state",
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    created_by_user_id: UUID | None = SqlField(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    general_access_role_id: UUID | None = SqlField(
        default=None,
        foreign_key="agent_access_roles.id",
        nullable=True,
        ondelete="RESTRICT",
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
    # Shared Template pin: active agents set exactly one of the shared or
    # Agent-owned pin columns (enforced by ck_agent_template_pin_state).
    platform_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="platform_template.id",
        nullable=True,
        ondelete="RESTRICT",
    )
    agent_template_override_version_id: UUID | None = SqlField(
        default=None,
        foreign_key="agent_template_override_version.id",
        nullable=True,
        ondelete="RESTRICT",
    )
    agent_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="agent_template.id",
        nullable=True,
        ondelete="RESTRICT",
    )
    model: str = SqlField(nullable=False, default="")
    # The model this Agent's running pod was started on. The runtime reads its config
    # once at container start, so this stays put while `model` and the Organization
    # default move underneath it. Empty means "not running".
    running_model: str = SqlField(
        default="",
        sa_column=Column(sa.String(), nullable=False, server_default=""),
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

    ingest_key_encrypted: str | None = SqlField(default=None, nullable=True)
    communication_key_encrypted: str | None = SqlField(default=None, nullable=True)
    approval_mode: CommandApprovalMode = SqlField(
        default=CommandApprovalMode.AUTO,
        sa_column=Column(sa.String(10), nullable=False, server_default="auto"),
    )


class AgentAccess(BaseModel, table=True):
    __tablename__: str = "agent_access"
    __table_args__ = (
        sa.UniqueConstraint(
            "membership_id",
            "agent_id",
            name="uq_agent_access_membership_agent",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "organization_id"],
            ["user_organization.id", "user_organization.organization_id"],
            name="fk_agent_access_membership_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_access_agent_organization",
            ondelete="CASCADE",
        ),
        sa.Index("ix_agent_access_membership", "membership_id"),
        sa.Index("ix_agent_access_agent", "agent_id"),
        sa.Index("ix_agent_access_role", "access_role_id"),
    )

    organization_id: UUID = SqlField(
        foreign_key="organization.id",
        nullable=False,
        ondelete="CASCADE",
    )
    membership_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    access_role_id: UUID = SqlField(
        foreign_key="agent_access_roles.id",
        nullable=False,
        ondelete="RESTRICT",
    )


class AgentSecret(BaseModel, table=True):
    __tablename__: str = "agent_secret"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", "provider", name="uq_agent_secret_agent_provider"),
        sa.CheckConstraint(
            "(shared_credential_id IS NULL AND content IS NOT NULL) OR "
            "(shared_credential_id IS NOT NULL AND content IS NULL)",
            name="ck_agent_secret_content_xor_shared",
        ),
        sa.Index("ix_agent_secret_shared_credential_id", "shared_credential_id"),
    )

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    provider: SecretProvider = SqlField(sa_column=Column(sa.String(), nullable=False))
    secret_name: str = SqlField(nullable=False, max_length=255)  # predefined label
    content: str | None = SqlField(
        sa_column=Column(sa.Text(), nullable=True)
    )  # Fernet-encrypted JSON blob; NULL when shared_credential_id is set
    shared_credential_id: UUID | None = SqlField(
        default=None,
        foreign_key="shared_credential.id",
        nullable=True,
        ondelete="RESTRICT",
    )


class AgentSkill(BaseModel, table=True):
    __tablename__: str = "agent_skill"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill_agent_skill"),
        sa.ForeignKeyConstraint(
            ["skill_id", "pinned_version"],
            ["skill_version.skill_id", "skill_version.version"],
            ondelete="NO ACTION",
            name="fk_agent_skill_pinned_version",
        ),
    )

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="CASCADE")
    # The exact skill version this agent mounts at start. Skills are pinned
    # explicitly (like template pins): publishing a newer version never moves an
    # existing pin, and recovering from a bad version means re-pinning to an
    # older one. Backfilled to each skill's then-latest at migration.
    pinned_version: int = SqlField(nullable=False)


class AgentLogSnapshot(BaseModel, table=True):
    __tablename__: str = "agent_log_snapshot"

    __table_args__ = (
        Index(
            "ix_agent_log_snapshot_agent_ended",
            "agent_id",
            sa.text("session_ended_at DESC"),
        ),
    )

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    session_started_at: datetime = SqlField(
        nullable=False,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    session_ended_at: datetime = SqlField(
        nullable=False,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    log_text: str = SqlField(sa_column=Column(sa.Text(), nullable=False))
    byte_size: int = SqlField(nullable=False)


class AgentLifecycleEmailReceipt(BaseModel, table=True):
    """Idempotency record: a recipient has already been emailed for an Event Delivery.

    Keyed by (delivery_id, recipient_email) rather than event_id alone because a single
    delivery attempt can fan out to several recipients, and a retry must only re-notify
    the recipients that failed last time.
    """

    __tablename__: str = "agent_lifecycle_email_receipt"

    __table_args__ = (
        sa.UniqueConstraint(
            "delivery_id", "recipient_email", name="uq_agent_lifecycle_email_receipt_delivery_recipient"
        ),
    )

    delivery_id: UUID = SqlField(foreign_key="event_delivery.id", nullable=False, ondelete="CASCADE")
    recipient_email: str = SqlField(nullable=False, max_length=320)


class AgentTemplateSkill(BaseModel, table=True):
    __tablename__: str = "agent_template_skill"

    __table_args__ = (
        sa.UniqueConstraint("template_id", "skill_id", name="uq_agent_template_skill"),
        sa.Index("ix_agent_template_skill_template", "template_id"),
    )

    template_id: UUID = SqlField(foreign_key="agent_template.id", nullable=False, ondelete="CASCADE")
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="RESTRICT")
    # Rows on the same template sharing a non-NULL group_key form an "at least
    # one of" requirement group (e.g. GitHub OR Bitbucket). NULL means the
    # skill is a standalone AND-required skill, as it always was before groups.
    group_key: str | None = SqlField(default=None, nullable=True, max_length=100)


class AgentTemplateOverrideDraft(BaseModel, table=True):
    __tablename__: str = "agent_template_override_draft"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", name="uq_agent_template_override_draft_agent"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_template_override_draft_agent_organization",
            ondelete="CASCADE",
        ),
        sa.Index("ix_agent_template_override_draft_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    created_by_user_id: UUID | None = SqlField(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="SET NULL",
    )
    source_type: AgentTemplateOverrideSourceType = SqlField(
        sa_column=Column(sa.String(20), nullable=False),
    )
    source_template_key: str = SqlField(nullable=False, max_length=255)
    source_template_version: int = SqlField(nullable=False)
    source_platform_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="platform_template.id",
        nullable=True,
        ondelete="SET NULL",
    )
    source_agent_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="agent_template.id",
        nullable=True,
        ondelete="SET NULL",
    )
    template_name: str = SqlField(nullable=False, max_length=255)
    description: str | None = SqlField(default=None, nullable=True, max_length=500)
    soul_md: str = SqlField(nullable=False)
    identity_md: str = SqlField(nullable=False)
    user_md: str = SqlField(nullable=False)
    tools_md: str = SqlField(nullable=False)
    agents_md: str = SqlField(nullable=False)
    boot_md: str = SqlField(nullable=False)
    bootstrap_md: str = SqlField(nullable=False)
    heartbeat_md: str = SqlField(nullable=False)


class AgentTemplateOverrideVersion(BaseModel, table=True):
    __tablename__: str = "agent_template_override_version"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_template_override_version_agent_version"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_template_override_version_agent_organization",
            ondelete="CASCADE",
        ),
        sa.Index("ix_agent_template_override_version_organization", "organization_id"),
        sa.Index("ix_agent_template_override_version_agent", "agent_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    version: int = SqlField(nullable=False)
    created_by_user_id: UUID | None = SqlField(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="SET NULL",
    )
    source_type: AgentTemplateOverrideSourceType = SqlField(
        sa_column=Column(sa.String(20), nullable=False),
    )
    source_template_key: str = SqlField(nullable=False, max_length=255)
    source_template_version: int = SqlField(nullable=False)
    source_platform_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="platform_template.id",
        nullable=True,
        ondelete="SET NULL",
    )
    source_agent_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="agent_template.id",
        nullable=True,
        ondelete="SET NULL",
    )
    template_name: str = SqlField(nullable=False, max_length=255)
    description: str | None = SqlField(default=None, nullable=True, max_length=500)
    soul_md: str = SqlField(nullable=False)
    identity_md: str = SqlField(nullable=False)
    user_md: str = SqlField(nullable=False)
    tools_md: str = SqlField(nullable=False)
    agents_md: str = SqlField(nullable=False)
    boot_md: str = SqlField(nullable=False)
    bootstrap_md: str = SqlField(nullable=False)
    heartbeat_md: str = SqlField(nullable=False)


class AgentTemplateOverrideDraftSkill(BaseModel, table=True):
    __tablename__: str = "agent_template_override_draft_skill"

    __table_args__ = (
        sa.UniqueConstraint("draft_id", "skill_id", name="uq_agent_template_override_draft_skill"),
        sa.Index("ix_agent_template_override_draft_skill_draft", "draft_id"),
    )

    draft_id: UUID = SqlField(
        foreign_key="agent_template_override_draft.id",
        nullable=False,
        ondelete="CASCADE",
    )
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="RESTRICT")
    group_key: str | None = SqlField(default=None, nullable=True, max_length=100)


class AgentTemplateOverrideVersionSkill(BaseModel, table=True):
    __tablename__: str = "agent_template_override_version_skill"

    __table_args__ = (
        sa.UniqueConstraint("version_id", "skill_id", name="uq_agent_template_override_version_skill"),
        sa.Index("ix_agent_template_override_version_skill_version", "version_id"),
    )

    version_id: UUID = SqlField(
        foreign_key="agent_template_override_version.id",
        nullable=False,
        ondelete="CASCADE",
    )
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="RESTRICT")
    group_key: str | None = SqlField(default=None, nullable=True, max_length=100)


class PlatformTemplateSkill(BaseModel, table=True):
    __tablename__: str = "platform_template_skill"

    __table_args__ = (
        sa.UniqueConstraint("template_id", "skill_id", name="uq_platform_template_skill"),
        sa.Index("ix_platform_template_skill_template", "template_id"),
    )

    template_id: UUID = SqlField(foreign_key="platform_template.id", nullable=False, ondelete="CASCADE")
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="RESTRICT")
    # Rows on the same template sharing a non-NULL group_key form an "at least
    # one of" requirement group (e.g. GitHub OR Bitbucket). NULL means the
    # skill is a standalone AND-required skill, as it always was before groups.
    group_key: str | None = SqlField(default=None, nullable=True, max_length=100)


class PlatformTemplateDraftSkill(BaseModel, table=True):
    __tablename__: str = "platform_template_draft_skill"

    # Mirrors PlatformTemplateSkill: the required-skill selection currently
    # staged on a Draft Template Version, carried over to platform_template_skill
    # on publish.
    __table_args__ = (
        sa.UniqueConstraint("draft_id", "skill_id", name="uq_platform_template_draft_skill"),
        sa.Index("ix_platform_template_draft_skill_draft", "draft_id"),
    )

    draft_id: UUID = SqlField(foreign_key="platform_template_draft.id", nullable=False, ondelete="CASCADE")
    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="RESTRICT")
    # None for a standalone (AND-required) skill; otherwise the key of the
    # "at least one of" group this skill belongs to on this draft.
    group_key: str | None = SqlField(default=None, nullable=True, max_length=100)


class AgentSecretCreate(PydanticBaseModel):  # no secret_name — backend stamps it
    provider: SecretProvider
    content: dict

    @model_validator(mode="after")
    def validate_provider_content(self) -> AgentSecretCreate:
        validate_content(self.provider, self.content)
        return self


class AgentSharedCredentialAttach(PydanticBaseModel):
    shared_credential_id: UUID


class SkillVersionPin(PydanticBaseModel):
    """An explicit skill version pin for an agent assignment."""

    skill_id: UUID
    version: int = Field(ge=1)


class AgentCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    agent_type: AgentType = AgentType.OPENCLAW
    # Template reference. The agent pins to template_version if given, else to
    # the lineage's latest version.
    template_key: str = Field(min_length=1, max_length=255)
    template_version: int | None = None
    model: str | None = None
    # Integration credentials (optional)
    secrets: list[AgentSecretCreate] = Field(default_factory=list)
    shared_credentials: list[AgentSharedCredentialAttach] = Field(default_factory=list)
    # Custom org skills to assign on creation (optional)
    skill_ids: list[UUID] = Field(default_factory=list)
    # Optional explicit version pins for skills in skill_ids. Skills without a
    # pin here are pinned to their latest version at creation time.
    skill_versions: list[SkillVersionPin] = Field(default_factory=list)
    approval_mode: CommandApprovalMode = CommandApprovalMode.AUTO

    @model_validator(mode="after")
    def validate_unique_secret_providers(self) -> AgentCreate:
        providers = [s.provider for s in self.secrets]
        if len(providers) != len(set(providers)):
            raise ValueError("Duplicate secret providers are not allowed")
        return self


class AgentUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Template re-pin: point the agent at a different (key, version). Both must
    # be provided together. Per-agent markdown editing is no longer supported —
    # persona changes happen by editing templates in the catalog.
    template_key: str | None = Field(default=None, min_length=1, max_length=255)
    template_version: int | None = None
    model: str | None = None
    skill_ids: list[UUID] = Field(default_factory=list)
    removed_skill_ids: list[UUID] = Field(default_factory=list)
    # Version pins for newly added skills and for re-pinning skills the agent
    # already has (skills not in skill_ids). Every entry must reference a skill
    # the agent ends up with.
    skill_versions: list[SkillVersionPin] = Field(default_factory=list)
    # Integration credentials: upsert (add/replace) + explicit removal.
    # Providers not mentioned in either list are left untouched.
    secrets: list[AgentSecretCreate] | None = None
    shared_credentials: list[AgentSharedCredentialAttach] | None = None
    removed_secret_providers: list[SecretProvider] | None = None
    approval_mode: CommandApprovalMode | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_template_slug(cls, values: object) -> object:
        if isinstance(values, dict) and "template_slug" in values:
            raise ValueError("template_slug is no longer supported; use template_key")
        return values

    @model_validator(mode="before")
    @classmethod
    def reject_null_approval_mode(cls, values: object) -> object:
        if isinstance(values, dict) and values.get("approval_mode", ...) is None:
            raise ValueError("approval_mode must be omitted rather than null")
        return values

    @model_validator(mode="after")
    def validate_skill_operations(self) -> AgentUpdate:
        overlap = set(self.skill_ids) & set(self.removed_skill_ids)
        if overlap:
            ids = ", ".join(str(i) for i in overlap)
            raise ValueError(f"Skill ID(s) cannot be both added and removed: {ids}")
        return self

    @model_validator(mode="after")
    def validate_template_repin(self) -> AgentUpdate:
        if (self.template_key is None) != (self.template_version is None):
            raise ValueError("template_key and template_version must be provided together")
        return self

    @model_validator(mode="after")
    def validate_secret_operations(self) -> AgentUpdate:
        upserts = [s.provider for s in self.secrets or []]
        if len(upserts) != len(set(upserts)):
            raise ValueError("Duplicate secret providers are not allowed")
        removed = set(self.removed_secret_providers or [])
        overlap = removed & set(upserts)
        if overlap:
            names = ", ".join(p.value for p in overlap)
            raise ValueError(f"Provider(s) cannot be both updated and removed: {names}")
        return self


class AgentOverrideAuthorRead(PydanticBaseModel):
    user_id: UUID | None
    email: str | None
    full_name: str | None


class AgentTemplateOverrideSkillGroup(PydanticBaseModel):
    group_key: str = Field(min_length=1, max_length=100)
    skill_ids: list[UUID] = Field(min_length=1)


class AgentTemplateOverrideRequiredSkillRead(PydanticBaseModel):
    id: UUID
    organization_id: UUID | None
    name: str
    source: str
    required_providers: list[str]
    tools_pointer: str | None
    group_key: str | None = None
    created_at: datetime
    updated_at: datetime


def _validate_override_skill_groups(
    standalone_ids: list[UUID],
    groups: list[AgentTemplateOverrideSkillGroup],
) -> None:
    seen_group_keys: set[str] = set()
    seen_in_groups: set[UUID] = set()
    for group in groups:
        if group.group_key in seen_group_keys:
            raise ValueError(f"Duplicate required-skill group_key: {group.group_key}")
        seen_group_keys.add(group.group_key)
        for skill_id in group.skill_ids:
            if skill_id in seen_in_groups:
                raise ValueError(f"Skill {skill_id} cannot belong to more than one required-skill group")
            seen_in_groups.add(skill_id)
    overlap = set(standalone_ids) & seen_in_groups
    if overlap:
        raise ValueError(
            f"Skills cannot be both standalone required and part of a group: {sorted(str(s) for s in overlap)}"
        )


class AgentTemplateOverrideDraftUpdate(PydanticBaseModel):
    expected_updated_at: datetime
    template_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    soul_md: str | None = None
    identity_md: str | None = None
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None
    required_skill_ids: list[UUID] | None = None
    required_skill_groups: list[AgentTemplateOverrideSkillGroup] | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> AgentTemplateOverrideDraftUpdate:
        fields = set(self.model_fields_set) - {"expected_updated_at"}
        if not fields:
            raise ValueError("At least one draft field must be provided")
        if "template_name" in fields and self.template_name is None:
            raise ValueError("template_name cannot be null when updating a draft")
        non_nullable_fields = {
            "soul_md",
            "identity_md",
            "user_md",
            "tools_md",
            "agents_md",
            "boot_md",
            "bootstrap_md",
            "heartbeat_md",
        }
        null_fields = sorted(field for field in fields if field in non_nullable_fields and getattr(self, field) is None)
        if null_fields:
            raise ValueError(f"Draft fields cannot be null: {', '.join(null_fields)}")
        if self.required_skill_ids is not None and self.required_skill_groups is not None:
            _validate_override_skill_groups(self.required_skill_ids, self.required_skill_groups)
        return self


class AgentTemplateOverridePublish(PydanticBaseModel):
    expected_updated_at: datetime


class AgentTemplateSelection(PydanticBaseModel):
    selection_type: Literal["platform", "organization", "override"]
    template_key: str | None = Field(default=None, min_length=1, max_length=255)
    template_version: int | None = Field(default=None, ge=1)
    override_version: int | None = Field(default=None, ge=1)
    expected_agent_updated_at: datetime

    @model_validator(mode="after")
    def validate_target(self) -> AgentTemplateSelection:
        if self.selection_type in {"platform", "organization"}:
            if self.template_key is None or self.template_version is None or self.override_version is not None:
                raise ValueError(
                    "Shared template selection requires template_key and template_version, and no override_version"
                )
        elif self.override_version is None or self.template_key is not None or self.template_version is not None:
            raise ValueError("Override selection requires override_version, and no template_key or template_version")
        return self


class AgentTemplateOverrideSnapshotRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    version: int | None
    template_key: str
    template_name: str
    description: str | None
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str
    source_type: AgentTemplateOverrideSourceType
    source_template_key: str
    source_template_version: int
    source_platform_template_id: UUID | None
    source_agent_template_id: UUID | None
    created_by_user_id: UUID | None
    author: AgentOverrideAuthorRead | None = None
    required_skills: list[AgentTemplateOverrideRequiredSkillRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentConfigurationVersionRead(AgentTemplateOverrideSnapshotRead):
    state: Literal["active", "published"] = "published"
    pin_type: AgentTemplatePinType = AgentTemplatePinType.SHARED
    template_source: str | None = None


class AgentTemplateOverrideDraftRead(AgentTemplateOverrideSnapshotRead):
    version: int | None = None
    state: Literal["draft"] = "draft"
    pin_type: AgentTemplatePinType = AgentTemplatePinType.OVERRIDE


class AgentTemplateOverrideVersionRead(AgentTemplateOverrideSnapshotRead):
    version: int
    state: Literal["published"] = "published"
    pin_type: AgentTemplatePinType = AgentTemplatePinType.OVERRIDE


class AgentConfigurationRead(PydanticBaseModel):
    agent_id: UUID
    active: AgentConfigurationVersionRead
    draft: AgentTemplateOverrideDraftRead | None = None
    source_update: AgentConfigurationVersionRead | None = None
    shared_versions: list[AgentConfigurationVersionRead] = Field(default_factory=list)
    override_versions: list[AgentTemplateOverrideVersionRead] = Field(default_factory=list)


class AgentSecretRead(PydanticBaseModel):  # label + provider only — no secret values
    model_config = ConfigDict(from_attributes=True)

    provider: SecretProvider
    secret_name: str
    shared_credential_id: UUID | None = None
    shared_credential_name: str | None = None


class AgentAccessRoleRead(PydanticBaseModel):
    id: UUID
    name: str
    permissions: list[PermissionKey]
    is_locked: bool


class AgentAccessCandidateRead(PydanticBaseModel):
    user_id: UUID
    email: str
    full_name: str | None = None
    organization_role: OrganizationRole
    is_pending: bool
    is_creator: bool


class AgentAccessMemberRead(AgentAccessCandidateRead):
    access_role: AgentAccessRoleRead


class AgentGeneralAccessRead(PydanticBaseModel):
    role: AgentAccessRoleRead | None


class AgentAccessSettingsAssignmentUpdate(PydanticBaseModel):
    user_id: UUID
    access_role_id: UUID


class AgentAccessSettingsUpdate(PydanticBaseModel):
    general_access_role_id: UUID | None = None
    assignments: list[AgentAccessSettingsAssignmentUpdate] = Field(default_factory=list)


class AgentAccessSettingsRead(PydanticBaseModel):
    general_access: AgentGeneralAccessRead
    assignments: list[AgentAccessMemberRead]


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
    # The exact skill version this agent is pinned to (explicit, like templates).
    version: int


AgentModelSource = Literal["default", "override"]


class AgentRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: AgentStatus
    agent_type: AgentType
    organization_id: UUID
    template_key: str
    template_version: int
    template_pin_type: AgentTemplatePinType = AgentTemplatePinType.SHARED
    override_version: int | None = None
    # The stored value: empty means the Agent follows its Organization's default.
    model: str
    # Resolved for the caller so no client re-derives inheritance, and so an
    # inheriting Agent can name the model it will actually run.
    model_source: AgentModelSource
    #: What this Agent would start on now.
    effective_model: str
    #: What its running pod actually started on; "" when it is not running.
    running_model: str
    #: Set only when a running Agent's resolved model has moved since it started, so a
    #: surface can say what a restart would switch it to without recomputing the rule.
    pending_model: str
    secrets: list[AgentSecretRead] = Field(default_factory=list)
    skills: list[AgentAssignedSkillRead] = Field(default_factory=list)
    approval_mode: CommandApprovalMode
    allowed_actions: list[PermissionKey] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentFilter(PydanticBaseModel):
    status: AgentStatus | None = None


class AgentHealthRead(PydanticBaseModel):
    status: str
    reason: str | None = None


def get_agent_filter(
    status: AgentStatus | None = Query(default=None),
) -> AgentFilter:
    return AgentFilter(status=status)


class AgentLogsRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    lines: list[str]
    source: str
    has_snapshots: bool = False
    snapshot_id: UUID | None = None
    session_started_at: datetime | None = None
    session_ended_at: datetime | None = None


class AgentLogHistoryRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    lines: list[str]
    has_more: bool
    session_ended_at: datetime | None = None
    next_snapshot_id: UUID | None = None
