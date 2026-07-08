"""AF-147: the `/users` list is a superuser-only *global* account admin view.

- Superusers see every account across all orgs, regardless of the active org.
- Everyone else (owners, admins, plain members) is forbidden — org-level people
  management lives on the per-org Members page instead.
"""

from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_length

from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_USERS = "/api/v1/users"

ORG_A = uuid7()
ORG_B = uuid7()

_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _org_a_populated():
    """Member in org A, owner in org B."""

    def step(context):
        there_is_a_user(
            email="member-a@example.com",
            organization_id=ORG_A,
            role=OrganizationRole.MEMBER,
        )(context)
        there_is_a_user(
            email="owner-b@example.com",
            organization_id=ORG_B,
            role=OrganizationRole.OWNER,
        )(context)

    return step


def test_org_owner_cannot_list_users():
    owner_id = uuid7()
    with given(
        [
            *_GIVEN,
            _org_a_populated(),
            there_is_a_user(
                id=owner_id,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
        ]
    ) as context:
        with when("an org owner (not a superuser) tries to list users"):
            response = context.client.get(
                _USERS,
                headers={**_auth(context), "X-Organization-Id": str(ORG_A)},
            )

            with then("it is forbidden — Users is superuser-only"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_plain_member_cannot_list_users():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=member_id,
                email="member-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        with when("a plain member tries to list users"):
            response = context.client.get(
                _USERS,
                headers={**_auth(context), "X-Organization-Id": str(ORG_A)},
            )

            with then("it is forbidden"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_superuser_lists_all_users_globally_even_with_active_org():
    super_id = uuid7()
    with given(
        [
            *_GIVEN,
            # Create the superuser first, before any org context is set, so the shared
            # user step doesn't try to attach them to an ambient organization.
            there_is_a_user(id=super_id, email="root@example.com", is_superuser=True),
            there_is_an_access_token_for_user(user_id=super_id),
            _org_a_populated(),
        ]
    ) as context:
        with when("a superuser lists users while an org is active in the header"):
            response = context.client.get(
                _USERS,
                headers={**_auth(context), "X-Organization-Id": str(ORG_A)},
            )

            with then("all users across orgs are returned — the view is global"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                # member-a + owner-b + the superuser itself (not scoped to ORG_A).
                assert_that(response.json()["items"], has_length(3))
