from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr
from sqlmodel import Column, Enum, Field, Index

from api.domains.organizations.models import OrganizationRead
from api.domains.rbac.catalog import OrganizationRole
from api.infrastructure.postgres.models import BaseModel


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
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_user_organization_id_organization",
        ),
    )
    user_id: UUID | None = Field(foreign_key="user.id", nullable=True, ondelete="SET NULL")
    organization_id: UUID = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
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


class OrganizationMemberRead(PydanticBaseModel):
    """A user's membership within one organization, for member-management UIs."""

    user_id: UUID
    email: str
    full_name: str | None = None
    role: OrganizationRole
    is_pending: bool  # invite not yet accepted (email unverified)


class AddMemberRequest(PydanticBaseModel):
    email: EmailStr
    full_name: str | None = None
    role: OrganizationRole = OrganizationRole.MEMBER


class ChangeMemberRoleRequest(PydanticBaseModel):
    role: OrganizationRole


class TransferOwnershipRequest(PydanticBaseModel):
    user_id: UUID


class MemberInviteResult(PydanticBaseModel):
    """Result of adding/resending an invite. ``invite_link`` is present only when an
    invite was actually (re)sent to a pending user."""

    member: OrganizationMemberRead
    invite_link: str | None = None


class InviteLinkResult(PydanticBaseModel):
    invite_link: str
