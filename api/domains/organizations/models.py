from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, EmailStr
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import CheckConstraint, Field

from api.infrastructure.postgres.models import BaseModel


class Organization(BaseModel, table=True):
    __tablename__: str = "organization"

    name: str = Field(nullable=False, min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)
    is_default: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}
    )
    allowed_models: list[str] = Field(
        default_factory=list, 
        sa_column=sa.Column(JSONB, server_default="[]")
    )

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
    is_default: bool
    owner_email: str | None = None
    owner_name: str | None = None
    allowed_models: list[str] = []


class OrganizationUpdate(PydanticBaseModel):
    name: str | None = Field(min_length=3, max_length=255, default=None)
    description: str | None = None
    allowed_models: list[str] | None = None


class OrganizationCreate(PydanticBaseModel):
    name: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, nullable=True)
    owner_email: EmailStr
    owner_name: str | None = None
    allowed_models: list[str] | None = None


class OrganizationCreateResult(PydanticBaseModel):
    """Result of enrolling a new org. ``invite_link`` is the set-password link for a
    newly invited owner (null when the owner was already an active user); it is exposed
    only on create/resend so an admin can also deliver it manually."""

    organization: OrganizationRead
    invite_link: str | None = None


class OrganizationFilter(PydanticBaseModel):
    search: str | None = Field(default=None)


def get_organization_filter(
    search: str | None = Query(default=None),
) -> OrganizationFilter:
    return OrganizationFilter(search=search)
