from collections.abc import Set as AbstractSet
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr
from pydantic import Field as PydanticField
from sqlalchemy import Column, DateTime, Index, UniqueConstraint
from sqlmodel.main import Field

from api.domains.auth.exceptions import ForbiddenException
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.infrastructure.postgres.models import BaseModel


class Token(PydanticBaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenData(PydanticBaseModel):
    user_id: str
    stamp: str


class RefreshTokenRequest(PydanticBaseModel):
    refresh_token: str


class SignupRequest(PydanticBaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class ForgotPasswordRequest(PydanticBaseModel):
    email: EmailStr


class PasswordResetRequest(PydanticBaseModel):
    token: str
    new_password: str


class AcceptInviteRequest(PasswordResetRequest):
    # The invitee sets their own name when accepting — it's authoritative (the inviter's
    # name, if any, is only a provisional label for the pending row).
    full_name: str = PydanticField(min_length=1)


class RefreshToken(BaseModel, table=True):
    __tablename__: str = "refresh_token"
    __table_args__ = (Index("ix_refresh_token_token", "token"),)

    token: str = Field()
    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    stamp: str


class PasswordResetToken(BaseModel, table=True):
    __tablename__: str = "password_reset_token"

    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    is_used: bool
    # SHA-256 hex of the opaque token handed to the user; only the hash is stored, so a
    # DB leak alone can't be used to accept an invite or reset a password.
    token_hash: str = Field(index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class UserSlackConfigToken(BaseModel, table=True):
    __tablename__: str = "user_slack_config_token"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_slack_config_token_user"),)

    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    access_token_encrypted: str = Field(nullable=False)
    refresh_token_encrypted: str = Field(nullable=False, default="")


class SlackConfigTokenSave(PydanticBaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)


class SlackConfigTokenRead(PydanticBaseModel):
    has_token: bool
    token_preview: str | None = None


class CurrentUserContext(PydanticBaseModel):
    user: User
    organization_ids: list[UUID] = Field(default_factory=list)
    user_organization_map: dict[UUID, OrganizationUser] = Field(default_factory=dict)
    current_user_organization: OrganizationUser | None = None

    def require_current_user_organization(self) -> OrganizationUser:
        if not self.current_user_organization:
            raise ForbiddenException(detail="You don't have permission for this organization.")
        return self.current_user_organization

    # --- Authorization helpers ---
    # Platform administrators can operate in explicit Organization context without a
    # persisted Membership. Centralized here (next to the membership map they read) so
    # services don't re-implement the branch, and so a new org-scoped endpoint can't
    # forget the platform-admin case. Role is always resolved against the passed
    # organization_id — never the request's active org — to keep cross-org escalation
    # impossible.

    def has_org_role(self, organization_id: UUID, roles: AbstractSet[OrganizationRole]) -> bool:
        if self.user.is_superuser:
            return True
        membership = self.user_organization_map.get(organization_id)
        return membership is not None and membership.role in roles

    def require_org_role(
        self,
        organization_id: UUID,
        roles: AbstractSet[OrganizationRole],
        detail: str = "You don't have permission for this organization.",
    ) -> None:
        if not self.has_org_role(organization_id, roles):
            raise ForbiddenException(detail=detail)

    def require_platform_admin(
        self,
        detail: str = "This action requires platform administrator access.",
    ) -> None:
        if not self.user.is_superuser:
            raise ForbiddenException(detail=detail)

    def require_superuser(self, detail: str = "This action requires a superuser.") -> None:
        self.require_platform_admin(detail=detail)
