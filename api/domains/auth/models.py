from datetime import datetime
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Index, UniqueConstraint
from sqlmodel.main import Field

from api.domains.auth.exceptions import ForbiddenException
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
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


class RefreshToken(BaseModel, table=True):
    __tablename__: str = "refresh_token"
    __table_args__ = (Index("ix_refresh_token_token", "token"),)

    token: str = Field()
    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    stamp: str


class PasswordResetTokenData(PydanticBaseModel):
    user_id: str
    jti: str


class PasswordResetToken(BaseModel, table=True):
    __tablename__: str = "password_reset_token"

    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    is_used: bool
    jti: str
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class UserSlackConfigToken(BaseModel, table=True):
    __tablename__: str = "user_slack_config_token"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_slack_config_token_user"),
    )

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
            raise ForbiddenException(
                detail="You don't have permission for this organization."
            )
        return self.current_user_organization
