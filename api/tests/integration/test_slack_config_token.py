from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to, is_not, none
from starlette.testclient import TestClient

from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_authenticated_user

_VALIDATE = "api.domains.auth.token_service.validate_config_access_token"
_URL = "/api/v1/auth/me/slack-config-token"

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
    there_is_authenticated_user(email="user@example.com", role=OrganizationRole.ADMIN),
]


def _headers(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def test_get_slack_config_token_when_none_stored():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I GET my slack config token"):
            response = client.get(_URL, headers=_headers(context))

            with then("it should indicate no token"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(False))
                assert_that(body["token_preview"], none())


@patch(_VALIDATE)
def test_save_and_get_slack_config_token(mock_validate):
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I save a config token"):
            response = client.put(
                _URL,
                json={
                    "access_token": "valid-access-token",
                    "refresh_token": "xoxe-valid-refresh",
                },
                headers=_headers(context),
            )

            with then("it should return has_token=true with preview"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(True))
                assert_that(body["token_preview"], is_not(none()))

        with when("I GET my slack config token"):
            response = client.get(_URL, headers=_headers(context))

            with then("it should still have the token"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(True))


def test_save_slack_config_token_rejects_xoxb():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I try to save a bot token"):
            response = client.put(
                _URL,
                json={"access_token": "xoxb-fake-token", "refresh_token": "xoxe-fake"},
                headers=_headers(context),
            )

            with then("it should be rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@patch(_VALIDATE)
def test_delete_slack_config_token(mock_validate):
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I save then delete a config token"):
            client.put(
                _URL,
                json={
                    "access_token": "valid-access-token",
                    "refresh_token": "xoxe-valid-refresh",
                },
                headers=_headers(context),
            )
            response = client.delete(_URL, headers=_headers(context))

            with then("delete should return 204"):
                assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

            with then("GET should show no token"):
                response = client.get(_URL, headers=_headers(context))
                body = response.json()
                assert_that(body["has_token"], equal_to(False))


@patch(_VALIDATE)
@patch(
    "api.domains.auth.token_service.rotate_refresh_token",
    return_value=("rotated-access", "rotated-refresh"),
)
@patch("api.domains.agents.slack_routes.create_slack_app", return_value="A12345")
def test_create_slack_app_via_api(mock_create, mock_rotate, mock_validate):
    with given(_GIVEN) as context:
        client: TestClient = context.client
        headers = _headers(context)

        client.put(
            _URL,
            json={
                "access_token": "valid-access-token",
                "refresh_token": "xoxe-valid-refresh",
            },
            headers=headers,
        )

        with when("I create a slack app"):
            response = client.post(
                f"/api/v1/organizations/{context.organization.id}/slack/apps",
                json={"name": "TestBot", "description": "A test bot"},
                headers=headers,
            )

            with then("it should return app_id and URLs"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["app_id"], equal_to("A12345"))
                assert "A12345" in body["bot_token_url"]
                assert "A12345" in body["app_token_url"]


def test_slack_config_token_requires_auth():
    with given(
        [
            set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I GET without auth"):
            response = client.get(_URL)

            with then("it should be 401"):
                assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
