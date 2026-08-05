from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_key
from starlette.testclient import TestClient

from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import (
    there_is_a_user,
    there_is_an_access_token_for_user,
    there_is_authenticated_user,
)


def test_platform_admin_can_create_user():
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-create@example.com",
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin creates a new user"):
            response = client.post(
                "/api/v1/platform/users",
                json={
                    "email": "newuser@example.com",
                    "full_name": "New User",
                    "organization_name": "New User Studio",
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("the user is created and returned"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            payload = response.json()
            assert_that(payload["user"]["email"], equal_to("newuser@example.com"))
            assert_that(payload["user"]["full_name"], equal_to("New User"))
            assert_that(payload["user"]["is_platform_admin"], equal_to(False))
            assert_that(payload["user"], has_key("id"))
            assert_that(payload["user"]["email_verified_at"], equal_to(None))
            assert_that(payload["organization"]["name"], equal_to("New User Studio"))
            assert_that(payload, has_key("invite_link"))

        with then("they are the owner of the newly created organization"):
            org_user_repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
            membership = org_user_repo.get_by_user_id_and_organization_id(
                UUID(payload["user"]["id"]), UUID(payload["organization"]["id"])
            )
            assert membership is not None
            assert_that(membership.role, equal_to(OrganizationRole.OWNER))


def test_create_user_with_legacy_role_field_returns_422():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-own@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={
                "email": "wannabe-owner@example.com",
                "password": "StrongPass123",
                "role": "OWNER",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_create_user_with_legacy_organization_id_returns_422():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-noorg@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={
                "email": "orphan@example.com",
                "password": "StrongPass123",
                "organization_id": str(uuid7()),
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_create_user_with_duplicate_email_returns_409():
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-dup@example.com",
                is_platform_admin=True,
            ),
            there_is_a_user(email="existing@example.com"),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin creates a user with an already taken email"):
            response = client.post(
                "/api/v1/platform/users",
                json={"email": "existing@example.com"},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 409 conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_user_with_legacy_password_field_returns_422():
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-weak@example.com",
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin creates a user with a weak password"):
            response = client.post(
                "/api/v1/platform/users",
                json={
                    "email": "weakpass@example.com",
                    "password": "123",
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it rejects the retired password field at the schema boundary"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_non_platform_admin_cannot_create_user():
    org_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization(id=org_id),
            there_is_authenticated_user(
                email="regular@example.com",
                is_platform_admin=False,
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        client: TestClient = context.client

        with when("a non-platform-admin tries to create a user"):
            response = client.post(
                "/api/v1/platform/users",
                json={
                    "email": "newuser@example.com",
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 403 forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
