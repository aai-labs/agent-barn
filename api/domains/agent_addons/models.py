"""Agent Add-ons: extra libraries and tools installed into one Agent after a Platform
Administrator approves the exact request.

An Organization Owner or Admin requests an add-on for one Agent, saying why. A Platform
Administrator approves, rejects or later revokes that exact request; nobody edits it. Approved
add-ons are installed into the Agent's own add-ons volume by the `install-addons` init
container the next time the Agent starts. See `docs/features/agent-addons.md`.
"""

import enum
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.agents.models import AgentStatus, AgentType
from api.infrastructure.postgres.models import BaseModel

# Pending and Approved add-ons an Agent may have at once.
MAX_ACTIVE_ADDONS_PER_AGENT = 20
MAX_REASON_LENGTH = 1000
MAX_REJECTION_REASON_LENGTH = 1000
MAX_COMMAND_LENGTH = 4000
MAX_URL_LENGTH = 2000


class AgentAddonKind(str, enum.Enum):
    PIP = "pip"
    NPM = "npm"
    GIT = "git"
    BINARY = "binary"
    COMMAND = "command"


class AgentAddonState(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


ACTIVE_ADDON_STATES = frozenset({AgentAddonState.PENDING, AgentAddonState.APPROVED})

# A kind is offered only where its tool is in the runtime image: pip through uv and the
# runtime's own Python, npm through Node, git and curl-free downloads through Python. Both
# pinned images carry all of them (checked by the runtime contract tests), so both offer every
# kind; dropping a tool from an image means dropping its kind here.
KINDS_BY_RUNTIME: dict[AgentType, tuple[AgentAddonKind, ...]] = {
    AgentType.HERMES: tuple(AgentAddonKind),
    AgentType.OPENCLAW: tuple(AgentAddonKind),
}

# Package names as their registries accept them. The install step builds its own argument
# from these, so nothing but a name and an exact version ever reaches pip or npm.
_PIP_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
# An exact PEP 440 version: no operators, wildcards, ranges or spaces.
_PIP_VERSION = re.compile(
    r"^(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[A-Za-z0-9.]+)?$"
)
_NPM_NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]{0,99}/)?[a-z0-9][a-z0-9._~-]{0,99}$")
# An exact semver version, as npm pins one: no ranges, tags or `latest`.
_NPM_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
# A directory or file name under /opt/addons: no path separators, no leading dot.
_LOCAL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# https only, with a host, and no user information: a credential in a URL would be stored and
# shown to every reviewer.
_HTTPS_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[^\s@]*)?$")

# Every name an add-on can carry, for reading one back where only its grammar is trusted.
ADDON_NAME_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]{0,99}/)?[A-Za-z0-9][A-Za-z0-9._~-]{0,99}$")


class AgentAddon(BaseModel, table=True):
    """One add-on request for one Agent, and where it stands.

    The request (`kind`, `name`, `spec`, `reason`) is never edited after it is made; a
    different add-on is a new request. `spec` holds the kind's pin: `version`; `url` and
    `commit`; `url` and `sha256`; or `command`.
    """

    __tablename__: str = "agent_addons"
    __table_args__ = (
        # The Agent and the add-on are always in the same Organization.
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_addons_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'REVOKED')", name="ck_agent_addons_state"
        ),
        sa.CheckConstraint("kind IN ('pip', 'npm', 'git', 'binary', 'command')", name="ck_agent_addons_kind"),
        sa.CheckConstraint(
            "(state = 'REJECTED') = (rejection_reason IS NOT NULL)", name="ck_agent_addons_rejection_reason"
        ),
        # One active add-on per kind and name on an Agent: two would install over each other.
        sa.Index(
            "uq_agent_addons_active_name",
            "agent_id",
            "kind",
            sa.text("lower(name)"),
            unique=True,
            postgresql_where=sa.text("state IN ('PENDING', 'APPROVED')"),
        ),
        sa.Index("ix_agent_addons_agent_state", "agent_id", "state"),
        sa.Index("ix_agent_addons_state_created", "state", "created_at"),
        sa.Index("ix_agent_addons_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    kind: AgentAddonKind = SqlField(sa_column=Column(sa.String(16), nullable=False))
    name: str = SqlField(nullable=False, max_length=214)
    spec: dict[str, str] = SqlField(sa_column=Column(JSONB, nullable=False))
    # Why the Organization wants it, as the requester wrote it.
    reason: str = SqlField(sa_column=Column(sa.Text, nullable=False))
    state: AgentAddonState = SqlField(
        default=AgentAddonState.PENDING,
        sa_column=Column(sa.String(16), nullable=False, server_default="PENDING"),
    )
    requested_by_user_id: UUID | None = SqlField(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    decided_by_user_id: UUID | None = SqlField(default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL")
    decided_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    rejection_reason: str | None = SqlField(default=None, sa_column=Column(sa.Text, nullable=True))


class AgentAddonEmailReceipt(BaseModel, table=True):
    """Idempotency record: a recipient has already been emailed for an Event Delivery.

    Same shape and reasoning as the Organization budget receipt: a delivery fans out to
    several recipients, and a retry must only re-notify the ones that failed.
    """

    __tablename__: str = "agent_addon_email_receipt"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_agent_addon_email_receipt_delivery_recipient"),
    )

    delivery_id: UUID = SqlField(nullable=False, index=True)
    recipient_email: str = SqlField(nullable=False, max_length=320)


# --- requests -----------------------------------------------------------------------------

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REASON_LENGTH)]


def _matches(pattern: re.Pattern[str], value: str, message: str) -> str:
    value = value.strip()
    if not pattern.fullmatch(value):
        raise ValueError(message)
    return value


class _AddonCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Why the Agent needs it. Shown to the reviewer and to the Agent itself.
    reason: Reason


class PipAddonCreate(_AddonCreate):
    kind: Literal[AgentAddonKind.PIP]
    name: str
    #: An exact version; the install pins `name==version`.
    version: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _matches(_PIP_NAME, value, "Use the package's name on PyPI, without extras or a version.")

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _matches(_PIP_VERSION, value.removeprefix("=="), "Use one exact version, such as 1.4.2.")


class NpmAddonCreate(_AddonCreate):
    kind: Literal[AgentAddonKind.NPM]
    name: str
    #: An exact version; the install pins `name@version`.
    version: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _matches(_NPM_NAME, value, "Use the package's name on npm, such as left-pad or @scope/tool.")

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _matches(_NPM_VERSION, value, "Use one exact version, such as 1.4.2.")


class GitAddonCreate(_AddonCreate):
    kind: Literal[AgentAddonKind.GIT]
    #: The directory it is cloned into, under /opt/addons/src.
    name: str
    url: str
    #: The full 40-character commit SHA it is checked out at.
    commit: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _matches(_LOCAL_NAME, value, "Use letters, digits, dots, dashes or underscores.")

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        if len(value) > MAX_URL_LENGTH:
            raise ValueError("The URL is too long.")
        return _matches(_HTTPS_URL, value, "Use an https:// URL without a user name or password.")

    @field_validator("commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        return _matches(_COMMIT_SHA, value.lower(), "Use the full 40-character commit SHA.")


class BinaryAddonCreate(_AddonCreate):
    kind: Literal[AgentAddonKind.BINARY]
    #: The file name it is saved as, under /opt/addons/bin.
    name: str
    url: str
    #: The SHA-256 of the file; the install refuses a download that does not match.
    sha256: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _matches(_LOCAL_NAME, value, "Use letters, digits, dots, dashes or underscores.")

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        if len(value) > MAX_URL_LENGTH:
            raise ValueError("The URL is too long.")
        return _matches(_HTTPS_URL, value, "Use an https:// URL without a user name or password.")

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        return _matches(_SHA256, value.lower(), "Use the file's SHA-256 as 64 hexadecimal characters.")


class CommandAddonCreate(_AddonCreate):
    kind: Literal[AgentAddonKind.COMMAND]
    #: A label for the add-on; the command decides what it installs.
    name: str
    #: Run verbatim with `bash -euo pipefail`; the reviewer approves exactly this text.
    command: Annotated[str, StringConstraints(min_length=1, max_length=MAX_COMMAND_LENGTH)]

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _matches(_LOCAL_NAME, value, "Use letters, digits, dots, dashes or underscores.")

    @field_validator("command")
    @classmethod
    def _command(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The command is empty.")
        return value


AgentAddonCreate = Annotated[
    PipAddonCreate | NpmAddonCreate | GitAddonCreate | BinaryAddonCreate | CommandAddonCreate,
    Field(discriminator="kind"),
]


def addon_spec(
    data: PipAddonCreate | NpmAddonCreate | GitAddonCreate | BinaryAddonCreate | CommandAddonCreate,
) -> dict[str, str]:
    """The kind's pin, as stored in `spec`."""
    match data:
        case PipAddonCreate() | NpmAddonCreate():
            return {"version": data.version}
        case GitAddonCreate():
            return {"url": data.url, "commit": data.commit}
        case BinaryAddonCreate():
            return {"url": data.url, "sha256": data.sha256}
        case CommandAddonCreate():
            return {"command": data.command}


def addon_summary(kind: AgentAddonKind | str, name: str, spec: Mapping[str, str | None]) -> str:
    """One line saying what an add-on installs, for emails and the Agent's instructions."""
    match AgentAddonKind(kind):
        case AgentAddonKind.PIP:
            return f"Python package {name}=={spec.get('version')}"
        case AgentAddonKind.NPM:
            return f"npm package {name}@{spec.get('version')}"
        case AgentAddonKind.GIT:
            return f"git repository {spec.get('url')} at commit {str(spec.get('commit'))[:12]}"
        case AgentAddonKind.BINARY:
            return f"binary {name} from {spec.get('url')}"
        case AgentAddonKind.COMMAND:
            return f"install command {name}"


class AgentAddonRejection(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REJECTION_REASON_LENGTH)
    ]


# --- reads --------------------------------------------------------------------------------


class AgentAddonSpecRead(PydanticBaseModel):
    """The pin, by kind: `version` (pip, npm), `url` and `commit` (git), `url` and `sha256`
    (binary), or `command`."""

    version: str | None = None
    url: str | None = None
    commit: str | None = None
    sha256: str | None = None
    command: str | None = None


class AgentAddonPersonRead(PydanticBaseModel):
    full_name: str | None
    email: str


class AgentAddonRead(PydanticBaseModel):
    """An add-on as the Organization sees it."""

    id: UUID
    agent_id: UUID
    kind: AgentAddonKind
    name: str
    spec: AgentAddonSpecRead
    reason: str
    state: AgentAddonState
    rejection_reason: str | None
    requested_by: AgentAddonPersonRead | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentAddonsRead(PydanticBaseModel):
    """One Agent's add-ons, newest first, with what may still be requested for it."""

    items: list[AgentAddonRead]
    #: The kinds its runtime offers.
    available_kinds: list[AgentAddonKind]
    #: How many Pending and Approved add-ons it may have at once.
    max_active: int = MAX_ACTIVE_ADDONS_PER_AGENT


class AgentAddonRow(NamedTuple):
    """An add-on with the requester's name, as the Organization's list reads it."""

    addon: AgentAddon
    requester_name: str | None
    requester_email: str | None


class PlatformAgentAddonRow(NamedTuple):
    """An add-on request as the Platform view reads it: a fixed column list.

    The request itself, which the reviewer needs, and the names that place it. Nothing else
    of the Agent: no configuration, prompts, logs or Secrets.
    """

    id: UUID
    organization_id: UUID
    organization_name: str
    agent_id: UUID
    agent_name: str
    agent_type: AgentType
    agent_deleted: bool
    kind: AgentAddonKind
    name: str
    spec: dict[str, str]
    reason: str
    state: AgentAddonState
    rejection_reason: str | None
    requester_name: str | None
    requester_email: str | None
    decider_name: str | None
    decider_email: str | None
    created_at: datetime
    decided_at: datetime | None
    updated_at: datetime


class PlatformAgentAddonRead(PydanticBaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    agent_id: UUID
    agent_name: str
    agent_type: AgentType
    #: The Agent was deleted; its add-ons stay as history.
    agent_deleted: bool
    kind: AgentAddonKind
    name: str
    spec: AgentAddonSpecRead
    reason: str
    state: AgentAddonState
    rejection_reason: str | None
    requested_by: AgentAddonPersonRead | None
    decided_by: AgentAddonPersonRead | None
    created_at: datetime
    decided_at: datetime | None
    updated_at: datetime


# --- what reaches the pod -----------------------------------------------------------------


class ApprovedAddon(NamedTuple):
    """An approved add-on as provisioning installs it, in install order."""

    id: UUID
    kind: AgentAddonKind
    name: str
    spec: dict[str, str]
    reason: str


def addons_set_digest(addons: list[ApprovedAddon]) -> str | None:
    """Identifies the approved set, in order; None when there is none.

    Recorded at start as `agent.running_addons_hash`, so a set approved or revoked since reads
    as pending. The `reason` is left out: it is shown to the Agent but installs nothing.
    """
    if not addons:
        return None
    canonical = [{"id": str(a.id), "kind": a.kind.value, "name": a.name, "spec": a.spec} for a in addons]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def addons_are_pending(status: AgentStatus, running_hash: str | None, current_hash: str | None) -> bool:
    """A running Agent whose pod installed a different approved set than there is now."""
    return status == AgentStatus.RUNNING and running_hash != current_hash
