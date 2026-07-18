from uuid import UUID, uuid7

from api.domains.auth.utils import set_default_org_id
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import system_role_id
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import LambdaWith
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def the_default_organization_id_is(org_id: UUID):
    """Set the global default-org fallback used when no X-Organization-Id header is
    sent, restoring it after the test."""

    def step(context):
        set_default_org_id(org_id)
        return LambdaWith(lambda: None, lambda: set_default_org_id(None))

    return step


def there_is_an_organization(
    name: str = "Test Organization",
    id: UUID | None = None,
    description: str = "A test organization",
    is_default: bool = False,
    owner_id: UUID | None = None,
):
    def step(context):
        organization_repository: OrganizationRepository = context.injector.get(
            OrganizationRepository
        )
        organization_user_repository: OrganizationUserRepository = context.injector.get(
            OrganizationUserRepository
        )

        org_owner_id = owner_id
        if org_owner_id is None and getattr(context, "user", None) is not None:
            org_owner_id = context.user.id

        if org_owner_id is None:
            there_is_a_user(email=f"owner-{uuid7()}@example.com", organization_id=None)(
                context
            )
            org_owner_id = context.user.id

        organization = Organization(
            id=id or uuid7(),
            name=name,
            description=description,
            is_default=is_default,
        )
        organization_repository.save(organization)

        org_user = organization_user_repository.get_by_user_id_and_organization_id(
            org_owner_id, organization.id
        )
        if org_user is None:
            org_user = OrganizationUser(
                user_id=org_owner_id,
                organization_id=organization.id,
                role_id=system_role_id(OrganizationRole.OWNER.value),
            )
            organization_user_repository.save(org_user)

        context.organization = organization
        context.organization_user = org_user

    return step


def there_is_an_organization_user(
    user_id: UUID,
    organization_id: UUID,
    role: OrganizationRole = OrganizationRole.ADMIN,
):
    def step(context):
        organization_user_repository: OrganizationUserRepository = context.injector.get(
            OrganizationUserRepository
        )
        user_organization = OrganizationUser(
            user_id=user_id,
            organization_id=organization_id,
            role_id=system_role_id(role.value),
        )
        organization_user_repository.save(user_organization)
        context.organization_user = user_organization

    return step


def there_is_a_default_organization(
    name: str = "Default Organization", id: UUID | None = None
):
    def step(context):
        there_is_an_organization(name=name, id=id, is_default=True)(context)

    return step


def there_is_an_organization_with_user_and_access_token(
    id: UUID | None = None,
    name: str = "Test Organization",
    email: str = "admin@example.com",
    user_id: UUID | None = None,
    role: OrganizationRole = OrganizationRole.OWNER,
):
    def step(context):
        there_is_a_user(email=email, id=user_id, role=role, organization_id=None)(
            context
        )
        there_is_an_organization(name=name, id=id, owner_id=context.user.id)(context)
        there_is_an_access_token_for_user()(context)

    return step
