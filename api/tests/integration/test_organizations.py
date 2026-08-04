from typing import cast
from uuid import UUID, uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    not_none,
)

from api.core.config import Config
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.models import User
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

_ORGS = "/api/v1/platform/organizations"
_SELF_SERVICE_ORGS = "/api/v1/organizations"

_GIVEN = [
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _there_is_a_platform_admin(email: str = "root@example.com"):
    super_id = uuid7()

    def step(context):
        there_is_a_user(id=super_id, email=email, is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id=super_id)(context)

    return step


def test_authenticated_user_creates_owned_organization():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="creator@example.com", organization_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        with when("an authenticated user creates an organization for themselves"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={
                    "name": "Creator Org",
                    "description": "Owned by its creator",
                },
                headers=_auth(context),
            )

        with then("the user is recorded as creator and initial owner"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            organization_id = UUID(response.json()["id"])

            organization_repo: OrganizationRepository = context.injector.get(OrganizationRepository)
            user_repo: UserRepository = context.injector.get(UserRepository)
            organization = organization_repo.get(organization_id)
            owner = user_repo.get_organization_owner(organization_id)

            assert_that(organization, not_none())
            organization = cast(Organization, organization)
            assert_that(organization.created_by_user_id, equal_to(context.user.id))
            assert_that(owner, not_none())
            owner = cast(User, owner)
            assert_that(owner.id, equal_to(context.user.id))


def test_organization_creator_cannot_exceed_creation_limit():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="limited@example.com", organization_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        for index in range(5):
            created = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": f"Limited Org {index}"},
                headers=_auth(context),
            )
            assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))

        with when("the creator attempts a sixth non-deleted organization"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": "Over Limit Org"},
                headers=_auth(context),
            )

        with then("creation is rejected with a clear conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("5"))


def test_platform_admin_uses_same_self_service_creation_and_quota():
    with given([*_GIVEN, _there_is_a_platform_admin()]) as context:
        for index in range(5):
            created = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": f"Admin Org {index}"},
                headers=_auth(context),
            )
            assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))

        with when("the platform admin attempts a sixth organization"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": "Admin Over Limit"},
                headers=_auth(context),
            )

        with then("platform privilege does not bypass the creator quota"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_self_service_creation_rejects_removed_provisioning_fields():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="creator@example.com", organization_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        with when("the old owner and model provisioning fields are submitted"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={
                    "name": "Legacy Contract Org",
                    "owner_email": "other@example.com",
                    "owner_name": "Other Owner",
                    "allowed_models": ["openai/gpt-5"],
                },
                headers=_auth(context),
            )

        with then("the removed contract is rejected rather than silently ignored"):
            assert_that(
                response.status_code,
                equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY),
            )


def test_self_service_creation_requires_authentication():
    with given([*_GIVEN]) as context:
        with when("an anonymous caller tries to create an organization"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": "Anonymous Org"},
            )

        with then("authentication is required"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_platform_organization_creation_operation_is_removed():
    with given([*_GIVEN, _there_is_a_platform_admin()]) as context:
        with when("a platform administrator calls the old provisioning route"):
            response = context.client.post(
                _ORGS,
                json={"name": "Legacy Platform Org"},
                headers=_auth(context),
            )

        with then("the operation is unavailable"):
            assert_that(response.status_code, equal_to(status.HTTP_405_METHOD_NOT_ALLOWED))


def test_new_organization_uses_platform_default_model():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="creator@example.com", organization_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        with when("the user creates an organization without model configuration"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": "Default Model Org"},
                headers=_auth(context),
            )

            with then("the organization receives the platform default model"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                expected_model = context.injector.get(Config).agent_default_model.removeprefix("litellm/openrouter/")
                assert_that(
                    response.json()["allowed_models"],
                    equal_to([expected_model]),
                )


def test_deleted_organization_releases_creator_quota():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="creator@example.com", organization_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        created_ids = []
        for index in range(5):
            created = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": f"Disposable Org {index}"},
                headers=_auth(context),
            )
            assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
            created_ids.append(created.json()["id"])

        deleted = context.client.delete(
            f"{_SELF_SERVICE_ORGS}/{created_ids[0]}",
            headers=_auth(context),
        )
        assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        with when("the creator replaces a deleted organization"):
            response = context.client.post(
                _SELF_SERVICE_ORGS,
                json={"name": "Replacement Org"},
                headers=_auth(context),
            )

        with then("only non-deleted organizations count toward the limit"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
