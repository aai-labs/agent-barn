"""Phase 3 (AF-147): invited users complete enrollment via POST /auth/set-password.

The set-password endpoint verifies the invite token, sets the password, marks the
email verified, and consumes the token — after which the user can log in.
"""

from fastapi import status
from hamcrest import assert_that, equal_to, is_, not_none
from starlette.testclient import TestClient

from api.domains.auth.service import AuthService
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user

_SET_PASSWORD = "/api/v1/auth/set-password"

_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _there_is_a_pending_invite(email: str = "invitee@example.com"):
    """Create an unverified user and stash a fresh invite token on the context."""

    def step(context):
        there_is_a_user(email=email, email_verified=False)(context)
        auth_service: AuthService = context.injector.get(AuthService)
        context.invite_token = auth_service.generate_password_reset_token(context.user.id)

    return step


def test_invited_user_sets_password_and_can_log_in():
    with given([*_GIVEN, _there_is_a_pending_invite()]) as context:
        client: TestClient = context.client

        with when("the invited user sets their password"):
            response = client.post(
                _SET_PASSWORD,
                json={
                    "token": context.invite_token,
                    "new_password": "StrongPass123",
                    "full_name": "Invited Person",
                },
            )

            with then("the request succeeds and the email is verified"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                user_repo: UserRepository = context.injector.get(UserRepository)
                refreshed = user_repo.get(context.user.id)
                assert refreshed is not None
                assert_that(refreshed.email_verified_at, is_(not_none()))
                assert_that(refreshed.full_name, equal_to("Invited Person"))

        with when("they log in with the new password"):
            login = client.post(
                "/api/v1/auth/login",
                data={
                    "grant_type": "password",
                    "username": "invitee@example.com",
                    "password": "StrongPass123",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            with then("login succeeds"):
                assert_that(login.status_code, equal_to(status.HTTP_200_OK))


def test_set_password_rejects_weak_password():
    with given([*_GIVEN, _there_is_a_pending_invite()]) as context:
        client: TestClient = context.client

        with when("the new password is too weak"):
            response = client.post(
                _SET_PASSWORD,
                json={
                    "token": context.invite_token,
                    "new_password": "123",
                    "full_name": "X",
                },
            )

            with then("it is rejected as a bad request"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_set_password_token_is_single_use():
    with given([*_GIVEN, _there_is_a_pending_invite()]) as context:
        client: TestClient = context.client

        with when("the token is used once"):
            first = client.post(
                _SET_PASSWORD,
                json={
                    "token": context.invite_token,
                    "new_password": "StrongPass123",
                    "full_name": "Invited Person",
                },
            )
            with then("the first use succeeds"):
                assert_that(first.status_code, equal_to(status.HTTP_200_OK))

        with when("the same token is reused"):
            second = client.post(
                _SET_PASSWORD,
                json={
                    "token": context.invite_token,
                    "new_password": "AnotherPass456",
                    "full_name": "Invited Person",
                },
            )
            with then("reuse is rejected"):
                assert_that(second.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_set_password_requires_a_name():
    with given([*_GIVEN, _there_is_a_pending_invite()]) as context:
        client: TestClient = context.client

        with when("the invitee omits their name"):
            response = client.post(
                _SET_PASSWORD,
                json={
                    "token": context.invite_token,
                    "new_password": "StrongPass123",
                },
            )

            with then("the request is rejected as unprocessable"):
                assert_that(
                    response.status_code,
                    equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY),
                )


def test_set_password_with_invalid_token_is_rejected():
    with given([*_GIVEN]) as context:
        client: TestClient = context.client

        with when("the token is garbage"):
            response = client.post(
                _SET_PASSWORD,
                json={
                    "token": "not-a-token",
                    "new_password": "StrongPass123",
                    "full_name": "X",
                },
            )

            with then("it is rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
