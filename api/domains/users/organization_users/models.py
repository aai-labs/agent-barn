import enum
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr
from sqlmodel import Field, Index

from api.domains.organizations.models import OrganizationRead
from api.domains.rbac.catalog import (
    MEMBER_ROLE_ID,
    OWNER_ROLE_ID,
    system_role_id,
    system_role_name,
)
from api.infrastructure.postgres.models import BaseModel


class OrganizationRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    OWNER = "OWNER"


# Authorization role tiers. Single source of truth so the same policy isn't re-spelled per
# endpoint (and can't drift): managers (owners + admins) run org/member management and see
# billing; a few destructive/sensitive actions (delete org, transfer ownership, removing or
# demoting another admin) are owner-only.
ORG_MANAGER_ROLES: frozenset[OrganizationRole] = frozenset(
    {OrganizationRole.OWNER, OrganizationRole.ADMIN}
)
ORG_OWNER_ONLY_ROLES: frozenset[OrganizationRole] = frozenset({OrganizationRole.OWNER})


class OrganizationUser(BaseModel, table=True):
    __tablename__: str = "user_organization"

    __table_args__ = (
        sa.Index(
            "uq_user_organization_one_owner_per_org",
            "organization_id",
            unique=True,
            postgresql_where=sa.text(f"role_id = '{OWNER_ROLE_ID}'::uuid"),
        ),
        Index("uq_user_organization", "user_id", "organization_id", unique=True),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_user_organization_id_organization",
        ),
    )
    user_id: UUID | None = Field(
        foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    organization_id: UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    role_id: UUID = Field(
        default=MEMBER_ROLE_ID,
        foreign_key="roles.id",
        nullable=False,
        ondelete="RESTRICT",
    )

    def __init__(self, **data: Any) -> None:
        compatibility_role = data.pop("role", None)
        if compatibility_role is not None:
            if "role_id" in data:
                raise ValueError("Provide role or role_id, not both")
            role = OrganizationRole(compatibility_role)
            data["role_id"] = system_role_id(role.value)
        super().__init__(**data)

    @property
    def role(self) -> OrganizationRole:
        """Compatibility view for the seeded system roles exposed by current APIs."""
        return OrganizationRole(system_role_name(self.role_id))

    @role.setter
    def role(self, value: OrganizationRole) -> None:
        self.role_id = system_role_id(value.value)


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
