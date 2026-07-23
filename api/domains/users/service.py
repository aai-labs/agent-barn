from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.hashing import check_hash, hash_text
from api.domains.auth.password_validation import validate_strong_password
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import (
    AdminUserCreate,
    User,
    UserCreateSuperAdmin,
    UserFilter,
    UserPasswordChange,
    UserRead,
    UserUpdate,
)
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.organization_users.service import OrganizationUserService
from api.domains.users.repository import UserRepository
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@dataclass
class UserService:
    user_repository: UserRepository
    organization_user_service: OrganizationUserService
    organization_user_repository: OrganizationUserRepository
    organization_repository: OrganizationRepository
    refresh_token_repository: RefreshTokenRepository
    config: Config

    def ensure_default_superuser(self) -> User:
        existing = self.user_repository.get_superuser()
        if existing:
            return existing
        email, password = self.config.super_user_credentials.split(":")
        full_name = self.config.super_user_full_name
        return self.create_superuser(email=email, password=password, full_name=full_name)

    def create_superuser(self, email: str, password: str, full_name: str | None = None) -> User:
        validate_strong_password(password)
        user_data = UserCreateSuperAdmin(email=email, full_name=full_name)
        user = User(
            **user_data.model_dump(),
            hashed_password=hash_text(password),
        )
        return self.user_repository.save(user)

    def create_user(self, data: AdminUserCreate) -> User:
        validate_strong_password(data.password)
        if data.role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use transfer-ownership to assign an owner",
            )
        if self.organization_repository.get(data.organization_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Superuser-provisioned: the admin sets the password directly, so the account is
        # active (verified) immediately — not a pending invite.
        user = User(
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_text(data.password),
            email_verified_at=datetime.now(timezone.utc),
        )
        self.user_repository.save(user)

        self.organization_user_repository.save(
            OrganizationUser(
                user_id=user.id,
                organization_id=data.organization_id,
                role=data.role,
            )
        )
        return user

    def get_user_by_id_and_organization_id(self, user_id: UUID, organization_id: UUID) -> User:
        user = self.user_repository.get_by_id_and_organization_id(user_id, organization_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )
        return user

    def get_user(self, user_id: UUID) -> User:
        user = self.user_repository.get(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )
        return user

    def get_user_by_email(self, email: str) -> User:
        user = self.user_repository.get_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with email {email} not found",
            )
        return user

    def to_user_read(self, user: User) -> UserRead:
        organization_users = self.organization_user_service.find_by_user_id(user.id)
        return UserRead(**user.model_dump(), organization_users=organization_users)

    def get_paginated_users(
        self,
        filters: UserFilter,
        context: CurrentUserContext,
        page: int = 1,
        page_size: int = 15,
    ) -> PaginatedItems[UserRead]:
        pagination = Pagination(page=page, size=page_size)
        # Global account admin (superuser-only route): list every account. Org-level
        # people management lives on the per-org Members page instead.
        del context  # scoping is intentionally global here
        paginated_users: PaginatedItems[User] = self.user_repository.find_all_paginated(
            pagination=pagination,
            query_filters=filters,
            organization_id=None,
        )

        return PaginatedItems[UserRead](
            items=[UserRead(**user.model_dump()) for user in paginated_users.items],
            total=paginated_users.total,
            page=paginated_users.page,
            page_size=paginated_users.page_size,
        )

    def update_current_user(self, user_id: UUID, user_data: UserUpdate) -> UserRead:
        user = self.get_user(user_id)
        for key, value in user_data.model_dump(exclude_unset=True).items():
            setattr(user, key, value)
        user = self.user_repository.save(user)
        return self.to_user_read(user)

    def verify_user_password(self, user_id: UUID, password: str) -> None:
        user = self.get_user(user_id)
        if not check_hash(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password")

    def change_password(self, user_id: UUID, password_data: UserPasswordChange) -> None:
        user = self.get_user(user_id)
        if not check_hash(password_data.old_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Old password is incorrect",
            )

        validate_strong_password(password_data.new_password)
        user.hashed_password = hash_text(password_data.new_password)
        user.security_stamp = uuid7().hex
        self.user_repository.save(user)

    def reset_user_password(self, user_id: UUID, new_password: str) -> None:
        validate_strong_password(new_password)
        user = self.get_user(user_id)
        user.hashed_password = hash_text(new_password)
        user.security_stamp = uuid7().hex
        self.user_repository.save(user)

    def delete_user(self, user_id: UUID, actor_id: UUID) -> None:
        if user_id == actor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )
        user = self.get_user(user_id)

        refresh_tokens = self.refresh_token_repository.get_by_user(user.id)
        if refresh_tokens:
            self.refresh_token_repository.delete_all_by(refresh_tokens)

        self.organization_user_repository.delete_all_by_user_id(user.id)
        self.user_repository.delete(user.id)
