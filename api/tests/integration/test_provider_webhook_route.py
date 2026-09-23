"""The shared /webhooks/{connection_id} route, exercised through Teams.

The route reads the raw body itself so a signed webhook can be verified. Teams is the one
provider authenticated by a bearer token instead, so these pin that its activities still
get through that route and that an unauthenticated one does not.
"""

from typing import Any
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.communications.models import CommunicationDelivery, CommunicationDirection
from api.infrastructure.msteams.client import TeamsAuthError
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_communications_server,
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

_APP_ID = "11111111-1111-4111-8111-111111111111"
_SERVICE_URL = "https://smba.trafficmanager.net/amer/"
_VERIFY = "api.domains.communications.plugins.teams.verify_inbound_jwt"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_TEAMS_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    prepare_communications_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.RUNNING),
]


def _create_teams_connection(context) -> dict[str, Any]:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "teams",
            "display_name": "Microsoft Teams",
            "settings": {"dm_policy": "open"},
            "credentials": {
                "app_id": _APP_ID,
                "app_password": "placeholder",
                "tenant_id": "22222222-2222-4222-8222-222222222222",
            },
        },
        headers={"Authorization": f"Bearer {context.access_token}"},
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()


def _activity() -> dict[str, Any]:
    return {
        "type": "message",
        "id": "1485983408511",
        "timestamp": "2026-08-25T09:18:44.211Z",
        "serviceUrl": _SERVICE_URL,
        "channelId": "msteams",
        "from": {"id": "29:1XJKJMvc5GBtc2JwZq0oj8tHZmzrQgFmB39ATiQWA85g", "name": "Megan Bowen"},
        "conversation": {"conversationType": "personal", "id": "a:17I0kl9EkpE1O9PH5TWrzrLNwnWWcfrU"},
        "recipient": {"id": "28:c9e8c047-2a74-40a2-b28a-b162d5f5327c", "name": "Aria"},
        "text": "Hello",
        "channelData": {"tenant": {"id": "72f988bf-86f1-41af-91ab-2d7cd011db47"}},
    }


def _accepts_only(token: str):
    def verify(authorization: str, app_id: str, *, service_url: str) -> None:
        if authorization != f"Bearer {token}":
            raise TeamsAuthError("Bot Framework token verification failed")

    return verify


def _inbound(context) -> list[CommunicationDelivery]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(
                select(CommunicationDelivery).where(
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND
                )
            ).all()
        )


def test_a_teams_activity_with_a_valid_token_is_accepted() -> None:
    with given(_GIVEN) as context:
        connection = _create_teams_connection(context)

        with when("Teams posts an activity with a token the plugin accepts"):
            with patch(_VERIFY, side_effect=_accepts_only("valid")):
                response = context.communications_client.post(
                    f"/communications/v1/webhooks/{connection['id']}",
                    json=_activity(),
                    headers={"Authorization": "Bearer valid"},
                )

        with then("it is accepted and queued as an ordinary conversation delivery"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(response.json()["accepted"], has_length(1))
            [delivery] = _inbound(context)
            assert_that(str(delivery.id), equal_to(response.json()["accepted"][0]["delivery_id"]))


def test_a_teams_activity_with_a_rejected_token_is_unauthorized() -> None:
    with given(_GIVEN) as context:
        connection = _create_teams_connection(context)

        with when("the token does not verify"):
            with patch(_VERIFY, side_effect=_accepts_only("valid")):
                response = context.communications_client.post(
                    f"/communications/v1/webhooks/{connection['id']}",
                    json=_activity(),
                    headers={"Authorization": "Bearer forged"},
                )

        with then("it is refused and nothing is queued"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_inbound(context), has_length(0))


def test_a_teams_activity_without_an_authorization_header_is_unauthorized() -> None:
    """This used to be a 422 from a required header. The header is optional now, because a
    caller that signs its body sends none, so the plugin is what refuses it."""
    with given(_GIVEN) as context:
        connection = _create_teams_connection(context)

        with when("no Authorization header is sent"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                json=_activity(),
            )

        with then("it is refused and nothing is queued"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_inbound(context), has_length(0))
