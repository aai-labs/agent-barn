from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject

from api.core.config import Config
from api.domains.auth.hashing import check_hash, hash_text
from api.domains.auth.password_validation import validate_strong_password
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.users.models import (
    User,
    UserCreateSuperAdmin,
    UserFilter,
    UserPasswordChange,
    UserRead,
    UserUpdate,
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
    refresh_token_repository: RefreshTokenRepository
    config: Config

    def ensure_default_superuser(self) -> User:
        email, password = self.config.super_user_credentials.split(":")
        existing = self.user_repository.get_by_email(email)
        if existing:
            return existing
        return self.create_superuser(email=email, password=password)

    def create_superuser(self, email: str, password: str, full_name: str | None = None) -> User:
        validate_strong_password(password)
        user_data = UserCreateSuperAdmin(email=email, full_name=full_name)
        user = User(
            **user_data.model_dump(),
            hashed_password=hash_text(password),
            email_verified_at=datetime.now(timezone.utc),
        )
        return self.user_repository.save(user)

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

    def get_paginated_users(self, filters: UserFilter, page: int = 1, page_size: int = 15) -> PaginatedItems[UserRead]:
        pagination = Pagination(page=page, size=page_size)
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

    def delete_user(self, user_id: UUID) -> None:
        user = self.get_user(user_id)

        refresh_tokens = self.refresh_token_repository.get_by_user(user.id)
        if refresh_tokens:
            self.refresh_token_repository.delete_all_by(refresh_tokens)

        self.organization_user_repository.delete_all_by_user_id(user.id)
        self.user_repository.delete(user.id)
