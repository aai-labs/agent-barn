"""Capacity limits: the ceilings a Platform Administrator enters by hand.

The namespace's ResourceQuota caps the total of every container's limits, and the tenant
service account cannot read it. So a Platform Administrator types the ceilings in, and the
Platform resource usage page compares them with what the namespace has committed (see
`docs/adr/2026-10-01-capacity-limits-entered-by-hand.md`).

This is the one thing the resource usage feature stores. Usage itself is never stored.
"""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

# A well-known id, so the primary key alone keeps this to a single row.
PLATFORM_RESOURCE_LIMITS_ID = UUID("00000000-0000-7000-8000-00000000c001")

# Bounds that no real cluster reaches; they only stop a typo from becoming a number that
# cannot be drawn (a petabyte, or a hundred thousand cores).
MAX_MEMORY_LIMIT_BYTES = 2**50
MAX_CPU_LIMIT_CORES = 100_000.0

MEMORY_LIMIT_SETTING = "memory_limit_bytes"
CPU_LIMIT_SETTING = "cpu_limit_cores"

SUBJECT_DISPLAY = "Platform resource limits"


class PlatformResourceLimits(BaseModel, table=True):
    """The one row of capacity limits, created on first save.

    Every limit is nullable and NULL means "no limit entered", so a platform that never
    opened the dialog needs no row. Further limits are added as more typed nullable columns,
    each keeping its own validation and its own change Event.
    """

    __tablename__: str = "platform_resource_limits"

    # Bytes, so a 70 GiB ceiling is exact. 64-bit: the bound above does not fit in 32.
    memory_limit_bytes: int | None = SqlField(default=None, sa_column=Column(sa.BigInteger(), nullable=True))
    cpu_limit_cores: float | None = SqlField(default=None, nullable=True)


class ResourceLimitsRead(PydanticBaseModel):
    memory_limit_bytes: int | None = None
    cpu_limit_cores: float | None = None
    # None until the first save.
    updated_at: datetime | None = None


class ResourceLimitsUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    # Omitting a field leaves the stored value alone; an explicit null clears it.
    memory_limit_bytes: int | None = Field(default=None, gt=0, le=MAX_MEMORY_LIMIT_BYTES)
    cpu_limit_cores: float | None = Field(default=None, gt=0, le=MAX_CPU_LIMIT_CORES, allow_inf_nan=False)
