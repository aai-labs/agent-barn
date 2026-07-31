from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import CheckConstraint, Field

from api.infrastructure.postgres.models import BaseModel


class Organization(BaseModel, table=True):
    __tablename__: str = "organization"

    name: str = Field(nullable=False, min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)
    created_by_user_id: UUID | None = Field(
        default=None,
        foreign_key="user.id",
        nullable=True,
        ondelete="RESTRICT",
        index=True,
    )
    allowed_models: list[str] = Field(default_factory=list, sa_column=sa.Column(JSONB, server_default="[]"))

    __table_args__ = (
        sa.Index("ix_organization_name", "name"),
        CheckConstraint("length(name) >= 3", name="check_name_length_min"),
        CheckConstraint("length(name) <= 255", name="check_name_length_max"),
    )


class OrganizationRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    allowed_models: list[str] = []


class PlatformOrganizationRead(PydanticBaseModel):
    """Dedicated read model for Platform View: adds immutable Creator identity on top
    of what OrganizationRead exposes to Organization members, per the Platform
    Oversight ADR (no reuse of Organization-scoped DTOs)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    owner_user_id: UUID | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    creator_user_id: UUID | None = None
    creator_email: str | None = None
    creator_name: str | None = None
    allowed_models: list[str] = []


class OrganizationUpdate(PydanticBaseModel):
    name: str | None = Field(min_length=3, max_length=255, default=None)
    description: str | None = None
    allowed_models: list[str] | None = None


class OrganizationCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)


class OrganizationFilter(PydanticBaseModel):
    search: str | None = Field(default=None)


def get_organization_filter(
    search: str | None = Query(default=None),
) -> OrganizationFilter:
    return OrganizationFilter(search=search)
