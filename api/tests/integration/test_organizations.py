"""Phase 2 (AF-147): superuser creates an organization and invites the first owner.

`POST /organizations` creates a non-default org, attaches the given owner as OWNER
(inviting them when they are new/unverified), and returns the set-password invite link
so the superuser can also deliver it manually.
"""

from typing import Any
from unittest.mock import patch
from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    is_,
    none,
    not_none,
)

from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_ORGS = "/api/v1/organizations"

_GIVEN = [
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _there_is_a_superuser(email: str = "root@example.com"):
    super_id = uuid7()

    def step(context):
        there_is_a_user(id=super_id, email=email, is_superuser=True)(context)
        there_is_an_access_token_for_user(user_id=super_id)(context)

    return step


def test_superuser_creates_organization_and_invites_owner():
    with given([*_GIVEN, _there_is_a_superuser()]) as context:
        with when("superuser creates an org with a brand-new owner email"):
            response = context.client.post(
                _ORGS,
                json={
                    "name": "Acme Inc",
                    "description": "Acme workspace",
                    "owner_email": "owner@acme.com",
                    "owner_name": "Acme Owner",
                },
                headers=_auth(context),
            )

            with then("the org is created and an invite link is returned"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["organization"]["name"], equal_to("Acme Inc"))
                assert_that(body["organization"]["is_default"], is_(False))
                assert_that(
                    body["organization"]["owner_email"], equal_to("owner@acme.com")
                )
                assert_that(body["invite_link"], not_none())
                assert_that(
                    body["invite_link"],
                    contains_string("/set-password?token="),
                )

            with then("the owner exists as a pending (unverified) OWNER"):
                user_repo: UserRepository = context.injector.get(UserRepository)
                org_repo: OrganizationRepository = context.injector.get(
                    OrganizationRepository
                )
                org_id = response.json()["organization"]["id"]
                owner = user_repo.get_organization_owner(org_id)
                assert_that(owner, not_none())
                assert_that(owner.email, equal_to("owner@acme.com"))
                assert_that(owner.email_verified_at, is_(none()))
                assert_that(org_repo.get(org_id).is_default, is_(False))


def test_new_organization_is_seeded_with_predefined_templates():
    """A newly created org must start with the predefined template catalog (skills are
    global, but templates are per-org and have to be seeded)."""
    from api.domains.templates.seeding import PREDEFINED_TEMPLATES

    with given([*_GIVEN, _there_is_a_superuser()]) as context:
        create = context.client.post(
            _ORGS,
            json={"name": "Seeded Inc", "owner_email": "owner@seeded.com"},
            headers=_auth(context),
        )
        assert_that(create.status_code, equal_to(status.HTTP_201_CREATED))
        org_id = create.json()["organization"]["id"]

        templates = context.client.get(
            "/api/v1/templates",
            headers={**_auth(context), "X-Organization-Id": org_id},
        )
        assert_that(templates.status_code, equal_to(status.HTTP_200_OK))
        assert_that(templates.json()["total"], equal_to(len(PREDEFINED_TEMPLATES)))


def test_non_superuser_cannot_create_organization():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                email="member@example.com",
                organization_id=uuid7(),
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        with when("a non-superuser attempts to create an org"):
            response = context.client.post(
                _ORGS,
                json={"name": "Nope Inc", "owner_email": "x@nope.com"},
                headers=_auth(context),
            )

            with then("it is forbidden"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_create_organization_short_name_is_rejected():
    with given([*_GIVEN, _there_is_a_superuser()]) as context:
        with when("the org name is too short"):
            response = context.client.post(
                _ORGS,
                json={"name": "ab", "owner_email": "owner@short.com"},
                headers=_auth(context),
            )

            with then("validation rejects it"):
                assert_that(
                    response.status_code,
                    equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY),
                )


def test_create_organization_with_existing_active_owner_sends_no_invite():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="existing@corp.com"),  # active, email verified
            _there_is_a_superuser(),
        ]
    ) as context:
        with when("superuser creates an org owned by an already-active user"):
            response = context.client.post(
                _ORGS,
                json={"name": "Corp Inc", "owner_email": "existing@corp.com"},
                headers=_auth(context),
            )

            with then("org is created, owner attached, but no invite link"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["invite_link"], is_(none()))

                user_repo: UserRepository = context.injector.get(UserRepository)
                org_id = body["organization"]["id"]
                owner = user_repo.get_organization_owner(org_id)
                assert_that(owner.email, equal_to("existing@corp.com"))


def test_create_organization_requires_auth():
    with given([*_GIVEN]) as context:
        with when("no auth token is provided"):
            response = context.client.post(
                _ORGS,
                json={"name": "Anon Inc", "owner_email": "a@anon.com"},
            )

            with then("it is unauthorized"):
                assert_that(
                    response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED)
                )

@patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models")
def test_get_organization_strips_model_prefixes(mock_list_models):
    mock_list_models.return_value = [{"id": "google/gemini"}, {"id": "openai/gpt-4"}]
    with given([*_GIVEN, _there_is_a_superuser()]) as context:
        with when("superuser creates an org with prefixed models"):
            response = context.client.post(
                _ORGS,
                json={
                    "name": "Model Inc",
                    "owner_email": "model@corp.com",
                    "allowed_models": ["litellm/openrouter/google/gemini", "litellm/openrouter/openai/gpt-4"],
                },
                headers=_auth(context),
            )
            
            with then("org is created and models are stripped"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["organization"]["allowed_models"], equal_to(["google/gemini", "openai/gpt-4"]))

        with when("I fetch the organization"):
            org_id = body["organization"]["id"]
            response2 = context.client.get(
                f"{_ORGS}/{org_id}",
                headers=_auth(context),
            )

        with then("the fetched organization has stripped prefixes"):
            body2 = response2.json()
            assert_that(body2["allowed_models"], equal_to(["google/gemini", "openai/gpt-4"]))
