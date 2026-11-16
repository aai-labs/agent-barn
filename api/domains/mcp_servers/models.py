import datetime
import enum
import re
from typing import Literal, Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.custom_api.request import parse_url
from api.infrastructure.postgres.models import BaseModel

#: Short enough that OpenClaw's `<identifier>__<tool>` keeps most of a tool's name inside
#: its 64-character limit; Hermes names tools `mcp__<identifier>__<tool>` without a limit.
IDENTIFIER_MAX_LENGTH = 20
OPENCLAW_TOOL_NAME_LIMIT = 64
MAX_FILTERED_TOOLS = 200


class McpServerScope(str, enum.Enum):
    """Which Agents may use an MCP server.

    `agent` is an Agent MCP Server: added for one Agent, by the people who edit that Agent,
    and never shared with another.
    """

    ALL_AGENTS = "all_agents"
    SELECTED_AGENTS = "selected_agents"
    AGENT = "agent"


class OrganizationMcpServer(BaseModel, table=True):
    """A remote MCP server registered for an Organization's Agents, or for one Agent.

    An Organization MCP Server (`agent_id` NULL) lends its credential to every Agent it is
    available to; an Agent MCP Server (`agent_id` set, scope `agent`) is that one Agent's.
    Either way it is reached only through the credential gateway and its credential is
    never materialized into a pod. `credentials_encrypted` holds
    `{"auth": {...}, "headers": [...]}` encrypted with the Agent credential key, the same
    shape Custom API connections use.

    `restricted` gates an Organization server: only Organization Owners and Admins may switch
    it on for an Agent or give an Agent its own credential for it.
    """

    __tablename__: str = "organization_mcp_server"
    __table_args__ = (
        # Organization servers share one identifier namespace; each Agent has its own for its
        # Agent servers. The services also keep an Agent server off every Organization
        # identifier, since both reach the Agent's runtime side by side.
        sa.Index(
            "uq_organization_mcp_server_identifier",
            "organization_id",
            "identifier",
            unique=True,
            postgresql_where=sa.text("agent_id IS NULL"),
        ),
        sa.Index(
            "uq_organization_mcp_server_agent_identifier",
            "agent_id",
            "identifier",
            unique=True,
            postgresql_where=sa.text("agent_id IS NOT NULL"),
        ),
        # The target of the attachment's composite foreign key, which keeps an Agent and
        # the server it attaches to in one Organization.
        sa.UniqueConstraint("id", "organization_id", name="uq_organization_mcp_server_id_organization"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_organization_mcp_server_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "scope IN ('all_agents', 'selected_agents', 'agent')", name="ck_organization_mcp_server_scope"
        ),
        sa.CheckConstraint("(scope = 'agent') = (agent_id IS NOT NULL)", name="ck_organization_mcp_server_agent_scope"),
        sa.CheckConstraint("NOT (restricted AND agent_id IS NOT NULL)", name="ck_organization_mcp_server_restricted"),
        sa.CheckConstraint(
            "tool_include IS NULL OR tool_exclude IS NULL", name="ck_organization_mcp_server_one_tool_filter"
        ),
        sa.Index("ix_organization_mcp_server_agent", "agent_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE", index=True)
    identifier: str = SqlField(max_length=IDENTIFIER_MAX_LENGTH)
    name: str = SqlField(max_length=120)
    description: str | None = SqlField(default=None, max_length=500)
    url: str = SqlField(max_length=2048)
    scope: str = SqlField(default=McpServerScope.SELECTED_AGENTS.value, max_length=20)
    enabled: bool = True
    restricted: bool = SqlField(default=False, sa_column_kwargs={"server_default": sa.false()})
    agent_id: UUID | None = SqlField(default=None, nullable=True)
    credentials_encrypted: str
    tool_include: list[str] | None = SqlField(default=None, sa_column=Column(sa.ARRAY(sa.String()), nullable=True))
    tool_exclude: list[str] | None = SqlField(default=None, sa_column=Column(sa.ARRAY(sa.String()), nullable=True))
    created_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class AgentMcpServerAttachment(BaseModel, table=True):
    """One Agent's opt-in to a Selected Agents server.

    Kept when the server's scope changes, so switching back to Selected Agents restores the
    earlier selection; it has no effect while the scope is All Agents.
    """

    __tablename__: str = "agent_mcp_server_attachment"
    __table_args__ = (
        sa.UniqueConstraint("agent_id", "mcp_server_id", name="uq_agent_mcp_server_attachment"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_mcp_server_attachment_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id", "organization_id"],
            ["organization_mcp_server.id", "organization_mcp_server.organization_id"],
            name="fk_agent_mcp_server_attachment_server_organization",
            ondelete="CASCADE",
        ),
        sa.Index("ix_agent_mcp_server_attachment_server", "mcp_server_id"),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    mcp_server_id: UUID = SqlField(nullable=False)


class AgentMcpGatewayToken(BaseModel, table=True):
    """The credential one Agent generation presents to the gateway's MCP route.

    One row per Agent, replaced at every start. It is valid only while its generation is the
    Agent's current integration runtime generation and the Agent runs, so a stop, a failed
    start or the next start revokes it without touching this row.
    """

    __tablename__: str = "agent_mcp_gateway_token"
    __table_args__ = (
        sa.UniqueConstraint("agent_id", name="uq_agent_mcp_gateway_token_agent"),
        sa.UniqueConstraint("token_hash", name="uq_agent_mcp_gateway_token_hash"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_mcp_gateway_token_agent_organization",
            ondelete="CASCADE",
        ),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    token_hash: str = SqlField(max_length=64)
    generation: UUID = SqlField(nullable=False)


class McpCredentialKind(str, enum.Enum):
    STATIC = "static"
    OAUTH = "oauth"


class McpCredentialStatus(str, enum.Enum):
    ACTIVE = "active"
    #: The OAuth server refused to refresh the grant; someone has to sign in again.
    NEEDS_SIGN_IN = "needs_sign_in"


class McpServerCredential(BaseModel, table=True):
    """A credential for one Organization MCP Server held apart from the server's own.

    Two owners share this table:

    - the Organization (`agent_id` NULL): only the OAuth grant of an OAuth server, because a
      token-based server keeps its Organization credential on the server row;
    - one Agent: that Agent's own credential for the server, either static (`auth` and
      `headers`, the server row's shape) or an OAuth grant. The gateway prefers it.

    `credentials_encrypted` holds the JSON for its kind, encrypted with the Agent credential
    key. An OAuth grant keeps the refresh token and the current access token with its
    expiry, so every gateway replica refreshes under the row lock and shares the result.
    """

    __tablename__: str = "mcp_server_credential"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["mcp_server_id", "organization_id"],
            ["organization_mcp_server.id", "organization_mcp_server.organization_id"],
            name="fk_mcp_server_credential_server_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_mcp_server_credential_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('static', 'oauth')", name="ck_mcp_server_credential_kind"),
        sa.CheckConstraint("status IN ('active', 'needs_sign_in')", name="ck_mcp_server_credential_status"),
        # The Organization's credential for a token-based server lives on the server row.
        sa.CheckConstraint("agent_id IS NOT NULL OR kind = 'oauth'", name="ck_mcp_server_credential_org_oauth"),
        sa.Index(
            "uq_mcp_server_credential_organization",
            "mcp_server_id",
            unique=True,
            postgresql_where=sa.text("agent_id IS NULL"),
        ),
        sa.Index(
            "uq_mcp_server_credential_agent",
            "mcp_server_id",
            "agent_id",
            unique=True,
            postgresql_where=sa.text("agent_id IS NOT NULL"),
        ),
        sa.Index("ix_mcp_server_credential_agent", "agent_id"),
    )

    organization_id: UUID = SqlField(nullable=False)
    mcp_server_id: UUID = SqlField(nullable=False)
    agent_id: UUID | None = SqlField(default=None, nullable=True)
    kind: str = SqlField(max_length=10)
    status: str = SqlField(default=McpCredentialStatus.ACTIVE.value, max_length=20)
    credentials_encrypted: str
    #: Who saved it or signed in; kept as provenance, never used for authorization.
    created_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


def derive_identifier(name: str) -> str:
    """Lowercase letters, digits and single hyphens, from the display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:IDENTIFIER_MAX_LENGTH].rstrip("-")


def openclaw_tool_name(identifier: str, tool: str) -> str:
    """The name OpenClaw registers an MCP tool under: `<server>__<tool>`, cut at 64."""
    return f"{identifier}__{tool}"[:OPENCLAW_TOOL_NAME_LIMIT]


class McpHeaderInput(DTO):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    # Omitted on an update to keep the saved value of a secret header of the same name.
    value: str | None = Field(default=None, max_length=8192)
    secret: bool = False


class McpAuthInput(DTO):
    """How Agent Barn authenticates to the server.

    `oauth` means an OAuth sign-in: the Organization's, or an Agent's own. `client_id` and
    `client_secret` are only for servers without dynamic client registration; leave them
    out and Agent Barn registers itself. `scope` overrides the scopes the server asks for.
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "bearer", "api_key", "oauth"]
    header_name: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=8192)
    client_id: str | None = Field(default=None, max_length=1024)
    client_secret: str | None = Field(default=None, max_length=8192)
    scope: str | None = Field(default=None, max_length=1024)


class McpStaticAuthInput(McpAuthInput):
    """An Agent's own credential for a token-based server: never `oauth`."""

    type: Literal["none", "bearer", "api_key"]  # type: ignore[assignment]


def _tool_names(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    names = []
    for name in value:
        name = name.strip()
        if not name or len(name) > 128 or any(ord(c) < 33 or ord(c) == 127 for c in name):
            raise ValueError("Tool names must be 1 to 128 printable characters without spaces")
        if name not in names:
            names.append(name)
    if len(names) > MAX_FILTERED_TOOLS:
        raise ValueError(f"A tool filter can name at most {MAX_FILTERED_TOOLS} tools")
    return names


class _ServerFields(DTO):
    model_config = ConfigDict(extra="forbid")

    @field_validator("url", check_fields=False)
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is not None:
            # No query: the URL is shown back to managers and kept in plain text, so it
            # must not be a place to put a key. Embedded path keys are still possible,
            # which is why only managers ever read it.
            parse_url(value, base=True)
        return value

    @field_validator("tool_include", "tool_exclude", check_fields=False)
    @classmethod
    def _tools(cls, value: list[str] | None) -> list[str] | None:
        return _tool_names(value)

    @model_validator(mode="after")
    def _one_filter(self) -> Self:
        if getattr(self, "tool_include", None) is not None and getattr(self, "tool_exclude", None) is not None:
            raise ValueError("Use either an include list or an exclude list, not both")
        return self


class AgentMcpServerCreate(_ServerFields):
    """An Agent MCP Server: everything an Organization server has but who may use it."""

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    url: str = Field(max_length=2048)
    enabled: bool = True
    auth: McpAuthInput = Field(default_factory=lambda: McpAuthInput(type="none"))
    headers: list[McpHeaderInput] = Field(default_factory=list, max_length=32)
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None

    @model_validator(mode="after")
    def _identifier(self) -> Self:
        self.name = self.name.strip()
        if not self.identifier:
            raise ValueError("Server name must contain a letter or number")
        return self

    @property
    def identifier(self) -> str:
        return derive_identifier(self.name)


class McpServerCreate(AgentMcpServerCreate):
    scope: Literal[McpServerScope.ALL_AGENTS, McpServerScope.SELECTED_AGENTS] = McpServerScope.SELECTED_AGENTS
    #: Only Organization Owners and Admins may switch it on for an Agent or give an Agent
    #: its own credential for it.
    restricted: bool = False


class AgentMcpServerUpdate(_ServerFields):
    """Partial update. The identifier never changes, so renaming keeps it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    enabled: bool | None = None
    auth: McpAuthInput | None = None
    headers: list[McpHeaderInput] | None = Field(default=None, max_length=32)
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None


class McpServerUpdate(AgentMcpServerUpdate):
    scope: Literal[McpServerScope.ALL_AGENTS, McpServerScope.SELECTED_AGENTS] | None = None
    restricted: bool | None = None


class McpServerProbeRequest(DTO):
    """A server that is not saved yet: just what connecting to it needs."""

    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2048)
    auth: McpAuthInput = Field(default_factory=lambda: McpAuthInput(type="none"))
    headers: list[McpHeaderInput] = Field(default_factory=list, max_length=32)
    # Lets the editor see OpenClaw's names for the identifier the name will produce.
    name: str | None = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        parse_url(value, base=True)
        return value


class McpHeaderRead(DTO):
    name: str
    secret: bool
    value: str | None = None


class McpServerRead(DTO):
    """`url`, `auth_type`, `auth_header_name` and `headers` are for managers only.

    Some MCP servers put a key in the URL's path, so the URL is as sensitive as the
    credential; a caller without `mcp_server.manage` gets them as null and empty.
    """

    id: UUID
    identifier: str
    name: str
    description: str | None
    scope: McpServerScope
    enabled: bool
    restricted: bool
    tool_include: list[str] | None
    tool_exclude: list[str] | None
    attachment_count: int
    agent_count: int
    url: str | None = None
    auth_type: str | None = None
    auth_header_name: str | None = None
    headers: list[McpHeaderRead] = Field(default_factory=list)
    #: For managers, an OAuth server's client: whether Agent Barn registered itself, and
    #: the client id (never the secret).
    oauth_client_id: str | None = None
    oauth_registered: bool | None = None
    #: Every member sees whether an OAuth server is signed in for the Organization (for an
    #: Agent server, for its Agent); null for a token-based server.
    sign_in: McpSignInRead | None = None
    #: Set for an Agent MCP Server: the Agent it belongs to.
    agent_id: UUID | None = None
    agent_name: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class McpSignInRead(DTO):
    status: Literal["signed_in", "needs_sign_in", "not_signed_in"]
    signed_in_at: datetime.datetime | None = None


McpServerRead.model_rebuild()


class McpToolRead(DTO):
    name: str
    description: str | None
    #: The name OpenClaw gives the tool, cut at 64 characters.
    openclaw_name: str
    truncated: bool
    #: Whether the server's tool filter lets Agents see it.
    visible: bool


class McpServerProbeRead(DTO):
    server_name: str | None
    server_version: str | None
    protocol_version: str
    tools: list[McpToolRead]
    warnings: list[str]


class AgentMcpServerRead(DTO):
    """One Organization MCP Server as it stands for one Agent."""

    id: UUID
    identifier: str
    name: str
    description: str | None
    scope: McpServerScope
    enabled: bool
    #: Only Organization Owners and Admins may switch it on or off for this Agent, or change
    #: this Agent's own credential for it.
    restricted: bool
    #: Whether this Agent has an attachment. Meaningful for Selected Agents servers; kept but
    #: without effect for All Agents ones.
    attached: bool
    #: Whether the Agent may use the server now: enabled, and All Agents or attached.
    active: bool
    #: `none`, `bearer`, `api_key` or `oauth`: what an Agent credential for it must be.
    auth_type: str
    #: Which credential the gateway uses for this Agent: its own, the Organization's, or
    #: none yet (an OAuth server nobody has signed in to).
    credential_source: Literal["agent", "organization", "missing"]
    #: The credential in use needs someone to sign in (again) before the Agent can use it.
    needs_sign_in: bool
    has_agent_credential: bool
    #: The shape of the Agent's own token-based credential, so it can be edited: never the
    #: token or a secret header's value. Null without one, or for an Agent sign-in.
    agent_credential: McpAgentCredentialRead | None = None


class McpAgentCredentialRead(DTO):
    auth_type: str
    auth_header_name: str | None = None
    headers: list[McpHeaderRead] = Field(default_factory=list)


AgentMcpServerRead.model_rebuild()


class AgentMcpServersRead(DTO):
    servers: list[AgentMcpServerRead]
    #: This Agent's own servers. Their URL and authentication shape are shown only to someone
    #: who may edit them (`agent.update` and `agent.secret.manage` on the Agent).
    agent_servers: list[McpServerRead] = Field(default_factory=list)
    #: Whether the caller may change restricted servers for this Agent.
    can_manage_restricted: bool = False
    #: The Agent is running with a different set of servers than it would start with now,
    #: so a restart is needed for its runtime to list the current ones.
    pending_restart: bool


class AgentMcpServersUpdate(DTO):
    """The complete set of Selected Agents servers this Agent is attached to."""

    model_config = ConfigDict(extra="forbid")
    attached_server_ids: list[UUID] = Field(default_factory=list, max_length=200)
    restart: bool = False


class McpSignInStart(DTO):
    authorize_url: str


class McpSignInComplete(DTO):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=8192)
    state: str = Field(min_length=1, max_length=8192)


class McpSignInResult(DTO):
    mcp_server_id: UUID
    agent_id: UUID | None


class AgentMcpCredentialUpdate(DTO):
    """An Agent's own credential for a token-based server, in the server row's shape."""

    model_config = ConfigDict(extra="forbid")
    auth: McpStaticAuthInput
    headers: list[McpHeaderInput] = Field(default_factory=list, max_length=32)
