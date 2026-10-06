from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_item, is_, none, not_
from starlette.testclient import TestClient

from api.domains.communications.models import CommunicationConnection
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    TEST_TELEGRAM_BOT_TOKEN,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_BASE_ENV = {
    "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
    "LITELLM_BASE_URL": "http://litellm:4000",
    "LITELLM_SECRET_NAME": "litellm",
    "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
    "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
    "SKIP_TELEGRAM_TOKEN_VALIDATION": "true",
}
_BOT_ENV = {
    "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:agentbarn-test-bot-token",
    "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
}
_NO_BOT_ENV = {"AGENTBARN_TELEGRAM_BOT_TOKEN": "", "AGENTBARN_TELEGRAM_BOT_USERNAME": ""}


def _given(env: dict[str, str]) -> list:
    return [
        set_env_variable({**_BASE_ENV, **env}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(),
    ]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _connections(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections"


def _platforms(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/communication-platforms"


_AGENTBARN_TELEGRAM = {"platform_key": "agentbarn_telegram", "display_name": "Agent Barn Telegram", "credentials": {}}
_OWN_TELEGRAM = {
    "platform_key": "telegram",
    "display_name": "Telegram",
    "credentials": {"bot_token": TEST_TELEGRAM_BOT_TOKEN},
}


def test_agentbarn_telegram_is_offered_when_the_shared_bot_is_configured() -> None:
    with given(_given(_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I list the Communication Platforms"):
            response = client.get(_platforms(context), headers=_auth(context))

        with then("Agent Barn Telegram is offered beside bring-your-own Telegram"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            keys = [item["key"] for item in response.json()]
            assert_that(keys, has_item("agentbarn_telegram"))
            assert_that(keys, has_item("telegram"))


def test_agentbarn_telegram_is_hidden_when_no_shared_bot_is_configured() -> None:
    with given(_given(_NO_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I list the Communication Platforms and try to add Agent Barn Telegram anyway"):
            listed = client.get(_platforms(context), headers=_auth(context))
            created = client.post(_connections(context), json=_AGENTBARN_TELEGRAM, headers=_auth(context))

        with then("it is neither offered nor accepted"):
            assert_that([item["key"] for item in listed.json()], not_(has_item("agentbarn_telegram")))
            assert_that(created.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_an_agent_connects_to_agentbarn_telegram_without_bringing_a_bot() -> None:
    with given(_given(_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I add Agent Barn Telegram with no credentials"):
            response = client.post(_connections(context), json=_AGENTBARN_TELEGRAM, headers=_auth(context))

        with then("the Connection is created and names the shared bot"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(
                response.json(),
                has_entries(
                    platform_key="agentbarn_telegram",
                    external_identity="@AgentBarnTestBot",
                    webhook_url=is_(none()),
                ),
            )


def test_an_agent_cannot_have_both_telegram_types_at_once() -> None:
    with given(_given(_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I add bring-your-own Telegram, then Agent Barn Telegram"):
            own = client.post(_connections(context), json=_OWN_TELEGRAM, headers=_auth(context))
            shared = client.post(_connections(context), json=_AGENTBARN_TELEGRAM, headers=_auth(context))

        with then("the second Telegram type is refused"):
            assert_that(own.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(shared.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(shared.json()["detail"], contains_string("already has a Telegram connection"))


def test_an_agent_on_agentbarn_telegram_cannot_also_add_its_own_bot() -> None:
    with given(_given(_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I add Agent Barn Telegram, then bring-your-own Telegram"):
            shared = client.post(_connections(context), json=_AGENTBARN_TELEGRAM, headers=_auth(context))
            own = client.post(_connections(context), json=_OWN_TELEGRAM, headers=_auth(context))

        with then("the second Telegram type is refused"):
            assert_that(shared.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(own.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(own.json()["detail"], contains_string("already has a Telegram connection"))


def test_removing_one_telegram_type_frees_the_agent_for_the_other() -> None:
    with given(_given(_BOT_ENV)) as context:
        client: TestClient = context.client

        with when("I add bring-your-own Telegram, remove it, then add Agent Barn Telegram"):
            own = client.post(_connections(context), json=_OWN_TELEGRAM, headers=_auth(context)).json()
            client.delete(f"{_connections(context)}/{own['id']}?revision={own['revision']}", headers=_auth(context))
            shared = client.post(_connections(context), json=_AGENTBARN_TELEGRAM, headers=_auth(context))

        with then("Agent Barn Telegram is accepted"):
            assert_that(shared.status_code, equal_to(status.HTTP_201_CREATED))


def _existing_agentbarn_telegram_connection():
    def step(context):
        context.injector.get(PostgresRepositoryDelegate).save(
            CommunicationConnection(
                organization_id=context.agent.organization_id,
                agent_id=context.agent.id,
                platform_key="agentbarn_telegram",
                display_name="Agent Barn Telegram",
                credentials_encrypted="unused",
                driver_key_encrypted="unused",
            )
        )

    return step


def test_existing_agentbarn_telegram_connections_stay_readable_without_the_shared_bot() -> None:
    with given([*_given(_NO_BOT_ENV), _existing_agentbarn_telegram_connection()]) as context:
        client: TestClient = context.client

        with when("an environment without the shared bot lists an Agent's Connections"):
            response = client.get(_connections(context), headers=_auth(context))

        with then("the existing Agent Barn Telegram Connection is still listed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that([item["platform_key"] for item in response.json()], equal_to(["agentbarn_telegram"]))
