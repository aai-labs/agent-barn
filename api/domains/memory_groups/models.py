from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlmodel import Field

from api.infrastructure.postgres.models import BaseModel


class MemoryGroup(BaseModel, table=True):
    """A named memory pool: the Agents in it share one Honcho workspace
    (`af-pool-<group id>`) and therefore see each other's memory. Membership is
    the opt-in — an Agent with no group has no shared memory."""

    __tablename__: str = "memory_group"

    organization_id: UUID = Field(
        foreign_key="organization.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    name: str = Field(nullable=False, min_length=1, max_length=255)

    # A group name is the operator-facing handle, unique within its org so the
    # picker never shows two indistinguishable groups.
    __table_args__ = (sa.UniqueConstraint("organization_id", "name", name="uq_memory_group_org_name"),)


class MemoryGroupRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    organization_id: UUID


class MemoryGroupCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class MemoryGroupUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
