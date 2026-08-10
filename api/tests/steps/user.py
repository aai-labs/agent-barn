from datetime import UTC, datetime
from uuid import UUID, uuid7

from api.domains.auth.hashing import hash_text
from api.domains.auth.models import CredentialClass, CurrentUserContext, TokenData
from api.domains.auth.service import AuthService
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository


def there_is_an_access_token_for_user(user_id: UUID | None = None):
    def step(context):
        auth_service: AuthService = context.injector.get(AuthService)
        user_repository: UserRepository = context.injector.get(UserRepository)

        user = context.user if user_id is None else user_repository.get(user_id)
        if not user:
            raise RuntimeError("No user found for token generation")

        token_data = TokenData(
            user_id=str(user.id), stamp=user.security_stamp, credential_class=CredentialClass.USER_SESSION
        )
        context.access_token = auth_service.create_access_token(data=token_data)

    return step


def there_is_a_user(
    name: str = "Test User",
    email: str = "john@example.com",
    password: str = "StrongPass123",
    id: UUID | None = None,
    role: OrganizationRole | None = None,
    is_platform_admin: bool = False,
    organization_id: UUID | None = None,
    organization_user_id: UUID | None = None,
    email_verified: bool = True,
):
    def step(context):
        user_repository: UserRepository = context.injector.get(UserRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization_user_repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)

        existing = user_repository.get_by_email(email)
        if existing is not None:
            user = existing
        else:
            user = User(
                id=id or uuid7(),
                email=email,
                hashed_password=hash_text(password),
                full_name=name,
                is_platform_admin=is_platform_admin,
                email_verified_at=datetime.now(UTC) if email_verified else None,
            )
            user_repository.save(user)

        context.user = user

        organization = getattr(context, "organization", None)
        org_id = organization_id
        if org_id is not None:
            organization = organization_repository.get(org_id)
            if organization is None:
                organization = Organization(id=org_id, name=f"test-org-{org_id}")
                organization_repository.save(organization)
            context.organization = organization
        elif organization is not None:
            org_id = organization.id

        organization_user = None
        organization_ids: list[UUID] = []
        user_organization_map: dict[UUID, OrganizationUser] = {}
        if org_id is not None:
            org_role = role or OrganizationRole.OWNER
            organization_user = organization_user_repository.get_by_user_id_and_organization_id(user.id, org_id)
            if organization_user is None:
                organization_user = OrganizationUser(
                    id=organization_user_id or uuid7(),
                    user_id=user.id,
                    organization_id=org_id,
                    role=org_role,
                )
                organization_user_repository.save(organization_user)
            organization_ids = [org_id]
            user_organization_map = {org_id: organization_user}

        context.organization_user = organization_user
        context.current_user_context = CurrentUserContext(
            user=user,
            organization_ids=organization_ids,
            user_organization_map=user_organization_map,
            current_user_organization=organization_user,
        )

    return step


def there_are_users(user_data: list[dict], organization_id: UUID | None = None):
    def step(context):
        users = []
        for data in user_data:
            there_is_a_user(
                id=data.get("id"),
                role=data.get("role", OrganizationRole.MEMBER),
                email=data["email"],
                organization_id=organization_id,
            )(context)
            users.append(context.user)
        context.users = users

    return step


def there_is_authenticated_user(
    role: OrganizationRole = OrganizationRole.OWNER,
    id: UUID | None = None,
    email: str = "auth-user@example.com",
    organization_id: UUID | None = None,
    is_platform_admin: bool = False,
    email_verified: bool = True,
):
    def step(context):
        there_is_a_user(
            id=id,
            role=role,
            email=email,
            organization_id=organization_id,
            is_platform_admin=is_platform_admin,
            email_verified=email_verified,
        )(context)
        there_is_an_access_token_for_user()(context)

    return step
