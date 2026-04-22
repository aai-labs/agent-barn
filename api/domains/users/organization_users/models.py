import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import Column, Enum, Field, Index

from api.domains.organizations.models import OrganizationRead
from api.infrastructure.postgres.models import BaseModel


class OrganizationRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    OWNER = "OWNER"


class OrganizationUser(BaseModel, table=True):
    __tablename__: str = "user_organization"

    __table_args__ = (
        sa.Index(
            "uq_user_organization_one_owner_per_org",
            "organization_id",
            unique=True,
            postgresql_where=sa.text("role = 'OWNER'"),
        ),
        Index("uq_user_organization", "user_id", "organization_id", unique=True),
    )
    user_id: UUID | None = Field(
        foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    organization_id: UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    role: OrganizationRole = Field(
        default=OrganizationRole.MEMBER,
        sa_column=Column(Enum(OrganizationRole), nullable=False),
    )


class OrganizationUserRead(PydanticBaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    organization_id: UUID
    role: OrganizationRole
    organization: OrganizationRead
