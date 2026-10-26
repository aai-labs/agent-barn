"""Agent Sizes: the platform's catalog of the CPU and memory an Agent's container runs with.

A Platform Administrator keeps the catalog and decides which sizes each Organization may
choose; nobody types in custom values. An Agent runs on the size its Organization chose for
it, or on the default (`is_default`). See `docs/features/agent-sizes.md`.

Requests and limits are stored apart because the namespace quota binds on `requests.memory`:
the request decides how many Agents fit, the limit how far one may grow.
"""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlmodel import Column, SQLModel
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

MIB = 1024**2
GIB = 1024**3

# Bounds no Agent should reach; they only stop a typo from becoming a pod no node can hold.
MAX_CPU_MILLICORES = 64_000
MAX_MEMORY_BYTES = 256 * GIB
MAX_NAME_LENGTH = 64

# The size every Agent ran on before sizes existed, seeded by the migration that created the
# table as the default. Kept here for tests that reset the catalog to it; the migration
# carries its own copy, as migrations do.
STANDARD_SIZE_ID = UUID("00000000-0000-7000-8000-00000000a51e")
STANDARD_SIZE_NAME = "Standard"
STANDARD_CPU_REQUEST_MILLICORES = 50
STANDARD_CPU_LIMIT_MILLICORES = 500
STANDARD_MEMORY_REQUEST_BYTES = 320 * MIB
STANDARD_MEMORY_LIMIT_BYTES = 1 * GIB

# The settings a change Event can name, in the order a change is recorded.
SIZE_SETTINGS = (
    "name",
    "cpu_request_millicores",
    "cpu_limit_millicores",
    "memory_request_bytes",
    "memory_limit_bytes",
    "enabled",
    "is_default",
    "sort_order",
)


class AgentSize(BaseModel, table=True):
    """One size in the catalog. Exactly one is the default, and the default is always enabled."""

    __tablename__: str = "agent_sizes"
    __table_args__ = (
        sa.CheckConstraint("cpu_request_millicores > 0", name="ck_agent_sizes_cpu_request_positive"),
        sa.CheckConstraint(
            "cpu_request_millicores <= cpu_limit_millicores", name="ck_agent_sizes_cpu_request_le_limit"
        ),
        sa.CheckConstraint("memory_request_bytes > 0", name="ck_agent_sizes_memory_request_positive"),
        sa.CheckConstraint("memory_request_bytes <= memory_limit_bytes", name="ck_agent_sizes_memory_request_le_limit"),
        sa.CheckConstraint("enabled OR NOT is_default", name="ck_agent_sizes_default_enabled"),
        sa.Index("uq_agent_sizes_default", "is_default", unique=True, postgresql_where=sa.text("is_default")),
    )

    name: str = SqlField(max_length=MAX_NAME_LENGTH, sa_column_kwargs={"unique": True})
    cpu_request_millicores: int
    cpu_limit_millicores: int
    # Bytes, so a size is exact; 64-bit, since 256Gi does not fit in 32.
    memory_request_bytes: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))
    memory_limit_bytes: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))
    enabled: bool = SqlField(default=True)
    is_default: bool = SqlField(default=False)
    sort_order: int = SqlField(default=0)


class OrganizationAgentSize(SQLModel, table=True):
    """A size an Organization may choose, beyond the default. No rows: it cannot choose.

    The default is always choosable and never stored here, so changing the default never
    leaves an Organization with a stale allowance.
    """

    __tablename__: str = "organization_agent_sizes"

    organization_id: UUID = SqlField(
        foreign_key="organization.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
    # Deleting a size withdraws it from every allowed set; Agents on it block the delete.
    agent_size_id: UUID = SqlField(
        foreign_key="agent_sizes.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )


class AgentSizeRead(PydanticBaseModel):
    id: UUID
    name: str
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_bytes: int
    memory_limit_bytes: int
    enabled: bool
    is_default: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    # Live Agents whose stored size this is, which keep starting on it even after it is
    # disabled or withdrawn. Scoped to one Organization when the list asks for one.
    agent_count: int = 0
    # On the default only: live Agents that follow it and move when it changes.
    following_agent_count: int = 0


def _name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be blank")
    return stripped


def check_requests_within_limits(cpu_request: int, cpu_limit: int, memory_request: int, memory_limit: int) -> None:
    """A container may not ask for more than it is allowed to use; Kubernetes refuses it."""
    if cpu_request > cpu_limit:
        raise ValueError("the CPU request must not exceed the CPU limit")
    if memory_request > memory_limit:
        raise ValueError("the memory request must not exceed the memory limit")


class AgentSizeCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    cpu_request_millicores: int = Field(gt=0, le=MAX_CPU_MILLICORES)
    cpu_limit_millicores: int = Field(gt=0, le=MAX_CPU_MILLICORES)
    memory_request_bytes: int = Field(gt=0, le=MAX_MEMORY_BYTES)
    memory_limit_bytes: int = Field(gt=0, le=MAX_MEMORY_BYTES)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return _name(value)

    @model_validator(mode="after")
    def _requests_within_limits(self) -> AgentSizeCreate:
        check_requests_within_limits(
            self.cpu_request_millicores,
            self.cpu_limit_millicores,
            self.memory_request_bytes,
            self.memory_limit_bytes,
        )
        return self


class AgentSizeUpdate(PydanticBaseModel):
    """A partial edit. Omitting a field leaves it alone.

    `is_default` only accepts true: making another size the default is how this one stops
    being it, so the catalog always has exactly one.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    cpu_request_millicores: int | None = Field(default=None, gt=0, le=MAX_CPU_MILLICORES)
    cpu_limit_millicores: int | None = Field(default=None, gt=0, le=MAX_CPU_MILLICORES)
    memory_request_bytes: int | None = Field(default=None, gt=0, le=MAX_MEMORY_BYTES)
    memory_limit_bytes: int | None = Field(default=None, gt=0, le=MAX_MEMORY_BYTES)
    enabled: bool | None = None
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        return None if value is None else _name(value)

    @field_validator("is_default")
    @classmethod
    def _only_becomes_default(cls, value: bool | None) -> bool | None:
        if value is False:
            raise ValueError("make another size the default instead")
        return value


class AgentSizeOption(PydanticBaseModel):
    """A size as an Organization sees it: what it is called and what it gives an Agent."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_bytes: int
    memory_limit_bytes: int
    is_default: bool


class OrganizationAgentSizesRead(PydanticBaseModel):
    """The sizes an Organization's Agents may be put on: the default, then the enabled sizes
    the platform allowed it. `can_choose` is false when that is only the default."""

    can_choose: bool
    sizes: list[AgentSizeOption]


class OrganizationAgentSizesUpdate(PydanticBaseModel):
    """The sizes an Organization may choose beyond the default. Empty: it cannot choose."""

    model_config = ConfigDict(extra="forbid")

    agent_size_ids: list[UUID] = Field(max_length=100)


class AgentSizeChoice(PydanticBaseModel):
    """The size an Agent should start on next. None follows the platform default."""

    model_config = ConfigDict(extra="forbid")

    agent_size_id: UUID | None


def size_resources(size: AgentSize) -> dict[str, int]:
    """The requests and limits a pod gets from a size, as `Agent.running_resources` records them."""
    return {
        "cpu_request_millicores": size.cpu_request_millicores,
        "cpu_limit_millicores": size.cpu_limit_millicores,
        "memory_request_bytes": size.memory_request_bytes,
        "memory_limit_bytes": size.memory_limit_bytes,
    }


def size_is_pending(running_resources: dict[str, int] | None, size: AgentSize) -> bool:
    """Whether a pod started with `running_resources` would get different ones from `size`
    at its next start. Compared by value, so editing the size an Agent is on counts as well
    as choosing another one; never pending for an Agent that is not running."""
    return running_resources is not None and running_resources != size_resources(size)
