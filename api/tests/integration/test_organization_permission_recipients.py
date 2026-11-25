"""Who in an Organization is emailed about something only some roles may see (AF-464).

Recipients follow the Permission, not a copied role list: whoever's role grants it
is emailed, and nobody else, not even a Platform Administrator outside the
Organization.
"""

import pytest
from hamcrest import assert_that, equal_to, has_item, is_not

from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import OrganizationRole, PermissionKey, organization_role_allows
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user


def a_member_with_role(email: str, role: OrganizationRole, name: str = "Test User"):
    """Joins the Organization in context with `role`."""
    return there_is_a_user(name=name, email=email, role=role)


def _given(*steps):
    return [
        prepare_injector(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_a_user(email="owner@example.com", organization_id=None),
        there_is_an_organization(),
        *steps,
    ]


def _recipients(context, organization_id=None) -> list[tuple[str, str | None]]:
    return context.injector.get(OrganizationLookupService).recipients_with_permission(
        organization_id or context.organization.id, PermissionKey.ANOMALY_READ
    )


@pytest.mark.parametrize("role", list(OrganizationRole))
def test_a_role_is_emailed_exactly_when_it_grants_the_permission(role):
    # An Organization has exactly one Owner, so the Owner case is the one it has.
    email = "owner@example.com" if role is OrganizationRole.OWNER else "someone@example.com"
    steps = [] if role is OrganizationRole.OWNER else [a_member_with_role(email, role)]
    with given(_given(*steps)) as context:
        emails = [address for address, _ in _recipients(context)]

        if organization_role_allows(role, PermissionKey.ANOMALY_READ):
            assert_that(emails, has_item(email))
        else:
            assert_that(emails, is_not(has_item(email)))


def test_owners_and_admins_see_unusual_activity_and_members_do_not():
    with given(
        _given(
            a_member_with_role("admin@example.com", OrganizationRole.ADMIN, name="An Admin"),
            a_member_with_role("member@example.com", OrganizationRole.MEMBER),
        )
    ) as context:
        assert_that(
            sorted(_recipients(context)),
            equal_to([("admin@example.com", "An Admin"), ("owner@example.com", "Test User")]),
        )


def test_another_organizations_owners_and_platform_administrators_are_not_emailed():
    with given(_given()) as context:
        first = context.organization
        # Users outside any Organization: without one in context, `there_is_a_user` joins none.
        context.organization = None
        there_is_a_user(email="platform@example.com", is_platform_admin=True)(context)
        there_is_a_user(email="other-owner@example.com")(context)
        there_is_an_organization(name="Other", owner_id=context.user.id)(context)

        assert_that(_recipients(context, first.id), equal_to([("owner@example.com", "Test User")]))
