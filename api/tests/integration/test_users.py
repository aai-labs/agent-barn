from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_key, not_none
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, when, then
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization,
)
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.steps.user import (
    there_is_a_user,
    there_is_an_access_token_for_user,
    there_is_authenticated_user,
)


def test_platform_admin_can_create_user():
    super_id = uuid7()
    org_id = uuid7()

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
            there_is_an_organization(id=org_id),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin creates a new user"):
            response = client.post(
                "/api/v1/platform/users",
                json={
                    "email": "newuser@example.com",
                    "password": "StrongPass123",
                    "full_name": "New User",
                    "organization_id": str(org_id),
                    "role": "ADMIN",
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("the user is created and returned"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            payload = response.json()
            assert_that(payload["email"], equal_to("newuser@example.com"))
            assert_that(payload["full_name"], equal_to("New User"))
            assert_that(payload["is_platform_admin"], equal_to(False))
            assert_that(payload, has_key("id"))

        with then("they are a member of the chosen org with the chosen role"):
            org_user_repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
            membership = org_user_repo.get_by_user_id_and_organization_id(UUID(payload["id"]), org_id)
            assert_that(membership, not_none())
            assert_that(membership.role, equal_to(OrganizationRole.ADMIN))

        with then("the new user can login"):
            login_response = client.post(
                "/api/v1/auth/login",
                data={
                    "username": "newuser@example.com",
                    "password": "StrongPass123",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert_that(login_response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(login_response.json(), has_key("access_token"))


def test_create_user_with_owner_role_returns_400():
    super_id = uuid7()
    org_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-own@example.com", is_platform_admin=True),
            there_is_an_organization(id=org_id),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={
                "email": "wannabe-owner@example.com",
                "password": "StrongPass123",
                "organization_id": str(org_id),
                "role": "OWNER",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_user_with_unknown_org_returns_404():
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
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_user_with_duplicate_email_returns_409():
    super_id = uuid7()
    org_id = uuid7()

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
            there_is_an_organization(id=org_id),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin creates a user with an already taken email"):
            response = client.post(
                "/api/v1/platform/users",
                json={
                    "email": "existing@example.com",
                    "password": "StrongPass123",
                    "organization_id": str(org_id),
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 409 conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_user_with_weak_password_returns_400():
    super_id = uuid7()
    org_id = uuid7()

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
            there_is_an_organization(id=org_id),
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
                    "organization_id": str(org_id),
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 400 bad request"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


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
                    "password": "StrongPass123",
                    "organization_id": str(org_id),
                },
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 403 forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_cannot_delete_self():
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
                email="super-self-delete@example.com",
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin tries to delete themselves"):
            response = client.delete(
                f"/api/v1/platform/users/{super_id}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 400 bad request"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_platform_admin_can_delete_another_user():
    super_id = uuid7()
    target_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-delete@example.com",
                is_platform_admin=True,
            ),
            there_is_a_user(
                id=target_id,
                email="target-delete@example.com",
                password="StrongPass123",
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin deletes another user"):
            response = client.delete(
                f"/api/v1/platform/users/{target_id}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 204 no content"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        with then("the deleted user cannot login"):
            login_response = client.post(
                "/api/v1/auth/login",
                data={
                    "username": "target-delete@example.com",
                    "password": "StrongPass123",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert_that(login_response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_platform_admin_can_reset_user_password():
    super_id = uuid7()
    target_id = uuid7()
    org_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-reset@example.com",
                is_platform_admin=True,
            ),
            there_is_a_user(
                id=target_id,
                email="target-reset@example.com",
                password="OldPass123",
            ),
            there_is_an_organization(id=org_id),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin resets another user's password"):
            response = client.post(
                f"/api/v1/platform/users/{target_id}/reset-password",
                json={"new_password": "NewStrong456"},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        with then("the user can login with the new password"):
            login_response = client.post(
                "/api/v1/auth/login",
                data={
                    "username": "target-reset@example.com",
                    "password": "NewStrong456",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert_that(login_response.status_code, equal_to(status.HTTP_200_OK))

        with then("the old password no longer works"):
            old_login = client.post(
                "/api/v1/auth/login",
                data={
                    "username": "target-reset@example.com",
                    "password": "OldPass123",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert_that(old_login.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_non_platform_admin_cannot_reset_password():
    org_id = uuid7()
    target_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=target_id,
                email="target-noreset@example.com",
            ),
            there_is_an_organization(id=org_id),
            there_is_authenticated_user(
                email="regular-noreset@example.com",
                is_platform_admin=False,
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        client: TestClient = context.client

        with when("a non-platform-admin tries to reset a password"):
            response = client.post(
                f"/api/v1/platform/users/{target_id}/reset-password",
                json={"new_password": "StrongPass123"},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 403 forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_reset_password_with_weak_password_returns_400():
    super_id = uuid7()
    target_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-weakreset@example.com",
                is_platform_admin=True,
            ),
            there_is_a_user(
                id=target_id,
                email="target-weakreset@example.com",
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        with when("super admin resets with a weak password"):
            response = client.post(
                f"/api/v1/platform/users/{target_id}/reset-password",
                json={"new_password": "123"},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("it returns 400 bad request"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
