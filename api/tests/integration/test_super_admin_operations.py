from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def test_super_admin_can_list_all_users():
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
                email="super-list-users@example.com",
                is_superuser=True,
                email_verified=False,
            ),
            there_is_a_user(email="user-a@example.com"),
            there_is_a_user(email="user-b@example.com"),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["items"], has_length(3))


def test_regular_user_cannot_list_users():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="regular-list-users@example.com"),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_super_admin_can_delete_any_user():
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
                id=super_id, email="super-delete-user@example.com", is_superuser=True
            ),
            there_is_a_user(
                id=target_id,
                email="target-delete-user@example.com",
                password="StrongPass123",
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/users/{target_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "target-delete-user@example.com",
                "password": "StrongPass123",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert_that(login_response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_super_admin_can_list_all_organizations():
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id, email="super-list-orgs@example.com", is_superuser=True
            ),
            there_is_a_user(email="owner-org-a@example.com", organization_id=uuid7()),
            there_is_a_user(email="owner-org-b@example.com", organization_id=uuid7()),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/organizations",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["items"], has_length(2))
