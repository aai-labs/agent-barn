from datetime import datetime
from uuid import uuid7
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field

from api.infrastructure.postgres.models import BaseModel
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUserRead,
)


class User(BaseModel, table=True):
    __tablename__: str = "user"
    __table_args__ = (
        Index("ix_user_email", "email", unique=True),
        Index("ix_user_is_superuser", "is_superuser"),
    )

    email: EmailStr = Field()
    full_name: str | None = None
    hashed_password: str
    is_superuser: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    security_stamp: str = Field(default_factory=lambda: uuid7().hex)
    email_verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class UserCreate(PydanticBaseModel):
    email: EmailStr
    full_name: str | None = None


class UserCreateSuperAdmin(UserCreate):
    is_superuser: bool = True


class UserRead(BaseModel):
    full_name: str | None = None
    email: str
    is_superuser: bool
    email_verified_at: datetime | None = None
    organization_users: list[OrganizationUserRead] | None = None


class AdminUserCreate(PydanticBaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class AdminPasswordReset(PydanticBaseModel):
    new_password: str


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
