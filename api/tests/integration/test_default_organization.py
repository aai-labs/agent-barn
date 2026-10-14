"""Membership-free existing accounts recover a private workspace automatically."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length

from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def _setup(*steps):
    return [
        prepare_injector(),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        *steps,
        there_is_an_access_token_for_user(),
    ]


def _ensure(context):
    return context.client.post(
        "/api/v1/organizations/default", headers={"Authorization": f"Bearer {context.access_token}"}
    )


def test_existing_user_receives_default_organization_and_owner_membership():
    with given(_setup(there_is_a_user(name="Jane Doe"))) as context:
        with when("their dashboard prepares its organization"):
            response = _ensure(context)
        with then("it creates an ordinary organization with platform defaults"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json(), has_entries(name="Jane's Organization", is_trial=False))
            organization = context.injector.get(OrganizationRepository).get(UUID(response.json()["id"]))
            assert_that(organization.llm_budget_usd, equal_to(100))
        with then("the account context contains its owner membership"):
            account = context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {context.access_token}"})
            memberships = account.json()["organization_users"]
            assert_that(memberships, has_length(1))
            assert_that(memberships[0], has_entries(role="OWNER", organization_id=response.json()["id"]))


def test_repeated_and_concurrent_recovery_creates_only_one_organization():
    with given(_setup(there_is_a_user())) as context:
        with when("two tabs prepare the account at the same time"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: _ensure(context), range(2)))
            repeated = _ensure(context)
        with then("each receives the same organization"):
            assert_that([response.status_code for response in responses], equal_to([200, 200]))
            assert_that({response.json()["id"] for response in [*responses, repeated]}, has_length(1))
            assert_that(context.injector.get(OrganizationUserRepository).get_by_user_id(context.user.id), has_length(1))


def test_existing_membership_is_reused_without_creating_another_organization():
    with given(_setup(there_is_an_organization(), there_is_a_user(role=OrganizationRole.MEMBER))) as context:
        with when("an account with a membership asks for its default organization"):
            response = _ensure(context)
        with then("the existing organization is returned"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json()["id"], equal_to(str(context.organization.id)))
            assert_that(context.injector.get(OrganizationUserRepository).get_by_user_id(context.user.id), has_length(1))


@pytest.mark.parametrize("verified", [False, True])
def test_unauthenticated_or_unverified_users_cannot_create_default_organizations(verified):
    with given(_setup(there_is_a_user(email_verified=verified))) as context:
        with when("a caller without a verified session requests recovery"):
            response = context.client.post("/api/v1/organizations/default") if verified else _ensure(context)
        with then("access is refused and no membership is created"):
            assert_that(response.status_code, equal_to(401 if verified else 403))
            assert_that(context.injector.get(OrganizationUserRepository).get_by_user_id(context.user.id), has_length(0))


def test_deleted_trial_cannot_be_replaced_with_an_unrestricted_organization():
    with given(_setup(there_is_a_user())) as context:
        context.user.signed_up_at = datetime.now(UTC)
        context.injector.get(UserRepository).save(context.user)
        with when("the account attempts recovery after deleting its trial"):
            response = _ensure(context)
        with then("the trial restriction remains in force"):
            assert_that(response.status_code, equal_to(403))
            assert_that(context.injector.get(OrganizationUserRepository).get_by_user_id(context.user.id), has_length(0))


def test_recovery_keeps_each_users_organization_private():
    with given(_setup(there_is_a_user(email="first@example.com"))) as context:
        first = _ensure(context)
        there_is_a_user(email="second@example.com")(context)
        there_is_an_access_token_for_user()(context)
        with when("another account prepares its own organization"):
            second = _ensure(context)
        with then("the organizations have separate memberships"):
            assert_that(second.status_code, equal_to(200))
            memberships = context.injector.get(OrganizationUserRepository).get_by_user_id(context.user.id)
            assert_that(memberships, has_length(1))
            assert_that(str(memberships[0].organization_id), equal_to(second.json()["id"]))
            forbidden = context.client.get(
                f"/api/v1/organizations/{first.json()['id']}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
            assert_that(forbidden.status_code, equal_to(403))
