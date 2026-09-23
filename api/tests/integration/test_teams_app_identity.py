"""CommunicationsService.get_teams_app_identity — which Microsoft app (and tenant) is behind an
agent's Teams connection, so SharePoint can sign in on that app. Never the app's secret."""

from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, contains_string, equal_to, is_not

from api.domains.communications.service import CommunicationsService
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_DISCORD_TOKEN_VALIDATION": "true",
            "SKIP_TEAMS_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
]

_TEAMS_APP_ID = "11111111-1111-4111-8111-111111111111"
_TEAMS_TENANT_ID = "22222222-2222-4222-8222-222222222222"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections"


def _create(context, payload: dict) -> dict:
    response = context.client.post(_base(context), json=payload, headers=_auth(context))
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _teams_payload() -> dict:
    return {
        "platform_key": "teams",
        "display_name": "Microsoft Teams",
        "credentials": {"app_id": _TEAMS_APP_ID, "app_password": "bot-secret", "tenant_id": _TEAMS_TENANT_ID},
    }


def _discord_payload() -> dict:
    return {
        "platform_key": "discord",
        "display_name": "Community Discord",
        "settings": {"allowed_channel_ids": ["channel-one"]},
        "credentials": {"bot_token": "token-one"},
    }


def test_returns_the_app_identity_of_the_agents_teams_connection() -> None:
    with given(_GIVEN) as context:
        connection = _create(context, _teams_payload())
        service: CommunicationsService = context.injector.get(CommunicationsService)

        with when("I read the Teams app identity for that agent and connection"):
            identity = service.get_teams_app_identity(context.agent.id, connection["id"])

        with then("the app id and tenant come back, and nothing secret"):
            assert_that(identity.app_id, equal_to(_TEAMS_APP_ID))
            assert_that(identity.tenant_id, equal_to(_TEAMS_TENANT_ID))
            assert_that(hasattr(identity, "app_password"), equal_to(False))
            assert_that(repr(identity), is_not(contains_string("bot-secret")))


def test_refuses_a_connection_that_belongs_to_another_agent() -> None:
    with given(_GIVEN) as context:
        connection = _create(context, _teams_payload())
        service: CommunicationsService = context.injector.get(CommunicationsService)

        with when("I ask for it under a different agent id"), pytest.raises(HTTPException) as exc:
            service.get_teams_app_identity(uuid4(), connection["id"])

        with then("it is treated as not found, so nothing leaks about other agents"):
            assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_refuses_a_connection_that_is_not_teams() -> None:
    with given(_GIVEN) as context:
        connection = _create(context, _discord_payload())
        service: CommunicationsService = context.injector.get(CommunicationsService)

        with when("I ask for Teams credentials from a Discord connection"), pytest.raises(HTTPException) as exc:
            service.get_teams_app_identity(context.agent.id, connection["id"])

        with then("it is refused"):
            assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_refuses_a_retired_teams_connection() -> None:
    with given(_GIVEN) as context:
        connection = _create(context, _teams_payload())
        retired = context.client.delete(
            f"{_base(context)}/{connection['id']}?revision={connection['revision']}", headers=_auth(context)
        )
        assert retired.status_code == status.HTTP_204_NO_CONTENT, retired.text
        service: CommunicationsService = context.injector.get(CommunicationsService)

        with when("I ask for credentials of the retired connection"), pytest.raises(HTTPException) as exc:
            service.get_teams_app_identity(context.agent.id, connection["id"])

        with then("it is refused"):
            assert_that(exc.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_refuses_a_disabled_teams_connection() -> None:
    with given(_GIVEN) as context:
        connection = _create(context, _teams_payload())
        disabled = context.client.patch(
            f"{_base(context)}/{connection['id']}",
            json={"enabled": False, "revision": connection["revision"]},
            headers=_auth(context),
        )
        assert disabled.status_code == status.HTTP_200_OK, disabled.text
        service: CommunicationsService = context.injector.get(CommunicationsService)

        with when("I ask for credentials of the disabled connection"), pytest.raises(HTTPException) as exc:
            service.get_teams_app_identity(context.agent.id, connection["id"])

        with then("it is refused as a conflict the user can fix by re-enabling it"):
            assert_that(exc.value.status_code, equal_to(status.HTTP_409_CONFLICT))
