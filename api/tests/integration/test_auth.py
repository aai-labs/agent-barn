from fastapi import status
from hamcrest import assert_that, equal_to, has_key, is_not, none
from starlette.testclient import TestClient

from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user


def test_i_can_login_and_get_tokens():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="test_user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I login with valid credentials"):
            response = client.post(
                "/api/v1/auth/login",
                data={
                    "grant_type": "password",
                    "username": "test_user@example.com",
                    "password": "password",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            with then("it should return access and refresh tokens"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                payload = response.json()
                assert_that(payload, has_key("access_token"))
                assert_that(payload, has_key("refresh_token"))
                assert_that(payload["token_type"], equal_to("bearer"))


def test_i_can_signup_and_user_is_created():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client
        user_repository: UserRepository = context.injector.get(UserRepository)

        with when("I sign up"):
            response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "signup@example.com",
                    "password": "StrongPass123",
                    "full_name": "Signup User",
                },
            )

            with then("tokens should be returned"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                payload = response.json()
                assert_that(payload["access_token"], is_not(none()))
                assert_that(payload["refresh_token"], is_not(none()))

            with then("a verified user should exist"):
                user = user_repository.get_by_email("signup@example.com")
                assert_that(user, is_not(none()))
                assert_that(user.email_verified_at, is_not(none()))
