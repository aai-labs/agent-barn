from dataclasses import dataclass
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject
from sqlmodel import Session

from api.core.config import Config
from api.domains.auth.hashing import check_hash, hash_text
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.password_validation import validate_strong_password
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.auth.service import AuthService
from api.domains.events import EventDeliveryDispatcher
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.exceptions import (
    LastPlatformAdministrator,
    PlatformPrivilegeAlreadySet,
)
from api.domains.users.models import (
    PlatformUserCreate,
    PlatformUserCreateResult,
    PlatformUserInviteResult,
    PlatformUserRead,
    User,
    UserCreatePlatformAdmin,
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
    event_delivery_dispatcher: EventDeliveryDispatcher
    auth_service: AuthService

    def ensure_default_platform_admin(self) -> User:
        existing = self.user_repository.get_platform_admin()
        if existing:
            return existing
        email, password = self.config.platform_admin_credentials.split(":")
        full_name = self.config.platform_admin_full_name
        return self.create_platform_admin(email=email, password=password, full_name=full_name)

    def create_platform_admin(self, email: str, password: str, full_name: str | None = None) -> User:
        validate_strong_password(password)
        user_data = UserCreatePlatformAdmin(email=email, full_name=full_name)
        user = User(
            **user_data.model_dump(),
            hashed_password=hash_text(password),
        )
        return self.user_repository.save(user)

    @staticmethod
    def _initial_organization_name(data: PlatformUserCreate) -> str:
        if data.organization_name:
            return data.organization_name
        identity = data.full_name or str(data.email).split("@", maxsplit=1)[0]
        return f"{identity}'s Organization"

    def create_platform_user(self, data: PlatformUserCreate) -> PlatformUserCreateResult:
        with Session(self.user_repository.delegate.engine, expire_on_commit=False) as session:
            if self.user_repository.get_by_email_with_session(str(data.email), session) is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email {data.email} already exists.",
                )

            prepared = self.auth_service.prepare_invite(
                session,
                email=str(data.email),
                full_name=data.full_name,
            )
            organization = self.organization_repository.save_with_session(
                Organization(
                    name=self._initial_organization_name(data),
                    created_by_user_id=prepared.user.id,
                    allowed_models=[self.config.agent_default_model.removeprefix("litellm/openrouter/")],
                ),
                session,
            )
            self.organization_user_repository.save_with_session(
                OrganizationUser(
                    user_id=prepared.user.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                ),
                session,
            )
            session.commit()

        self.auth_service.send_prepared_invite(prepared)
        organization_read = self.organization_repository.get_platform_read(organization.id)
        if organization_read is None or prepared.invite_link is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to complete user onboarding",
            )
        return PlatformUserCreateResult(
            user=self.to_platform_user_read(prepared.user),
            organization=organization_read,
            invite_link=prepared.invite_link,
        )

    def resend_platform_user_invite(self, user_id: UUID) -> PlatformUserInviteResult:
        user = self.get_user(user_id)
        if user.email_verified_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active user does not need an invitation",
            )
        invited_user, invite_link = self.auth_service.invite_user(
            email=user.email,
            full_name=user.full_name,
        )
        del invited_user
        if invite_link is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active user does not need an invitation",
            )
        return PlatformUserInviteResult(invite_link=invite_link)

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

    def to_platform_user_read(self, user: User) -> PlatformUserRead:
        organization_users = self.organization_user_service.find_platform_by_user_id(user.id)
        return PlatformUserRead(**user.model_dump(), organization_users=organization_users)

    def get_paginated_users(
        self,
        filters: UserFilter,
        context: CurrentUserContext,
        page: int = 1,
        page_size: int = 15,
    ) -> PaginatedItems[PlatformUserRead]:
        pagination = Pagination(page=page, size=page_size)
        # Global account admin (platform-admin-only route): list every account. Org-level
        # people management lives on the per-org Members page instead.
        del context  # scoping is intentionally global here
        paginated_users: PaginatedItems[User] = self.user_repository.find_all_paginated(
            pagination=pagination,
            query_filters=filters,
            organization_id=None,
        )

        return PaginatedItems[PlatformUserRead](
            items=[PlatformUserRead(**user.model_dump()) for user in paginated_users.items],
            total=paginated_users.total,
            page=paginated_users.page,
            page_size=paginated_users.page_size,
        )

    def change_platform_privilege(
        self,
        *,
        actor: CurrentUserContext,
        user_id: UUID,
        is_platform_admin: bool,
        reason: str,
    ) -> PlatformUserRead:
        if actor.user.id == user_id and not is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot revoke your own Platform Privilege",
            )
        try:
            changed = self.user_repository.change_platform_privilege(
                actor_id=actor.user.id,
                subject_id=user_id,
                is_platform_admin=is_platform_admin,
                reason=reason,
            )
        except PlatformPrivilegeAlreadySet as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Platform Privilege is already in the requested state",
            ) from error
        except LastPlatformAdministrator as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The final Platform Administrator cannot be revoked",
            ) from error
        if changed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )
        self.event_delivery_dispatcher.enqueue_immediate(changed.delivery_ids)
        return PlatformUserRead(**changed.user.model_dump())

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
