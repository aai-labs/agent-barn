from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid7

from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr, StringConstraints
from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field

from api.domains.organizations.models import PlatformOrganizationRead
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUserRead,
    PlatformOrganizationUserRead,
)
from api.infrastructure.postgres.models import BaseModel


class User(BaseModel, table=True):
    __tablename__: str = "user"
    __table_args__ = (
        Index("ix_user_email", "email", unique=True),
        Index("ix_user_is_platform_admin", "is_platform_admin"),
    )

    email: EmailStr = Field()
    full_name: str | None = None
    hashed_password: str
    is_platform_admin: bool = Field(default=False, sa_column_kwargs={"server_default": "false"})
    security_stamp: str = Field(default_factory=lambda: uuid7().hex)
    email_verified_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class UserCreate(PydanticBaseModel):
    email: EmailStr
    full_name: str | None = None


class UserCreatePlatformAdmin(UserCreate):
    is_platform_admin: bool = True


class UserRead(BaseModel):
    full_name: str | None = None
    email: str
    is_platform_admin: bool
    email_verified_at: datetime | None = None
    organization_users: list[OrganizationUserRead] | None = None


class PlatformUserRead(UserRead):
    """Platform View user read model with allowlisted membership organizations."""

    organization_users: list[PlatformOrganizationUserRead] | None = None


class PlatformUserCreate(PydanticBaseModel):
    model_config = {"extra": "forbid"}

    email: EmailStr
    full_name: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        ]
        | None
    ) = None
    organization_name: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=3, max_length=255),
        ]
        | None
    ) = None


class PlatformUserCreateResult(PydanticBaseModel):
    user: PlatformUserRead
    organization: PlatformOrganizationRead
    invite_link: str


class PlatformUserInviteResult(PydanticBaseModel):
    invite_link: str


class PlatformPrivilegeUpdate(PydanticBaseModel):
    is_platform_admin: bool
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ]


class UserUpdate(PydanticBaseModel):
    full_name: str | None = None


class UserPasswordChange(PydanticBaseModel):
    old_password: str
    new_password: str


class UserFilter(PydanticBaseModel):
    search: str | None = None
    organization_roles: list[OrganizationRole] | None = Query(default=None)
    user_ids: list[UUID] | None = None


def get_user_filter(
    search: str | None = None,
    organization_roles: list[OrganizationRole] | None = Query(default=None),
) -> UserFilter:
    return UserFilter(search=search, organization_roles=organization_roles)
