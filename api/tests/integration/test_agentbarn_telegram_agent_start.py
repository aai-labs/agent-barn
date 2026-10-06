import json
from unittest.mock import MagicMock

import yaml
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, is_not
from starlette.testclient import TestClient

from api.domains.agents.models import AgentType
from api.domains.communications.models import CommunicationConnection
from api.domains.communications.plugins.agentbarn_telegram import runtime_api_token, runtime_webhook_secret
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

_REAL_TOKEN = "424242:the-real-shared-bot-token"
_DRIVER_KEY = "driver-key-of-the-connection"
_COMMUNICATIONS = "http://communications.test:8002/communications/v1"


def _given(*, bot_configured: bool = True) -> list:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
                "COMMUNICATIONS_BASE_URL": _COMMUNICATIONS,
                # Agent Barn Telegram is always runtime-owned, whatever this says.
                "COMMUNICATIONS_NATIVE_PLATFORMS": "",
                "AGENTBARN_TELEGRAM_BOT_TOKEN": _REAL_TOKEN if bot_configured else "",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot" if bot_configured else "",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_a_template(),
    ]


def _agentbarn_telegram_connection(*, enabled: bool = True):
    def step(context) -> None:
        context.connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            enabled=enabled,
            credentials_encrypted=encrypt_token("{}", TEST_ENCRYPTION_KEY),
            driver_key_encrypted=encrypt_token(_DRIVER_KEY, TEST_ENCRYPTION_KEY),
        )
        context.injector.get(PostgresRepositoryDelegate).save(context.connection)

    return step


def _start(context) -> int:
    client: TestClient = context.client
    response = client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/start",
        headers={"Authorization": f"Bearer {context.access_token}"},
    )
    return response.status_code


def _created(context) -> tuple[dict, dict, list[str]]:
    k8s: MagicMock = context.injector.get(KubernetesClient)
    config_map = k8s.create_config_map.call_args.args[1].data
    secret = k8s.create_secret.call_args.args[1].string_data
    ports = [port.name for port in k8s.create_service.call_args.args[1].spec.ports]
    return config_map, secret, ports


def test_hermes_uses_agentbarn_telegram_through_the_proxy_without_the_real_token() -> None:
    with given(
        [*_given(), there_is_an_agent(agent_type=AgentType.HERMES), _agentbarn_telegram_connection()]
    ) as context:
        with when("a Hermes Agent with Agent Barn Telegram starts"):
            started = _start(context)

        with then("Hermes calls the proxy with its stand-in token and listens for forwarded updates"):
            assert_that(started, equal_to(status.HTTP_200_OK))
            config_map, secret, ports = _created(context)
            config = yaml.safe_load(config_map["hermes-config.yaml"])
            api_root = f"{_COMMUNICATIONS}/telegram/{context.connection.id}"
            assert_that(
                config["platforms"]["telegram"]["extra"],
                equal_to({"base_url": f"{api_root}/bot", "base_file_url": f"{api_root}/file/bot"}),
            )
            assert_that(secret["TELEGRAM_BOT_TOKEN"], equal_to(runtime_api_token(_DRIVER_KEY, _REAL_TOKEN)))
            assert_that(secret["TELEGRAM_WEBHOOK_SECRET"], equal_to(runtime_webhook_secret(_DRIVER_KEY)))
            assert_that(
                secret["TELEGRAM_WEBHOOK_URL"],
                equal_to(f"http://agent-{context.agent.id}.agent-farm.svc.cluster.local:8443/telegram"),
            )
            assert_that(ports, has_item("tg-webhook"))

        with then("the shared bot's real token is nowhere in the Agent's configuration"):
            assert_that(json.dumps(secret), is_not(contains_string("the-real-shared-bot-token")))
            assert_that(json.dumps(config_map), is_not(contains_string("the-real-shared-bot-token")))

        with then("the Agent is told how to send files, since its replies go through a native adapter"):
            assert_that(config_map["AGENTS.md"], contains_string("MEDIA:<absolute path>"))


def test_openclaw_uses_agentbarn_telegram_through_the_proxy_without_the_real_token() -> None:
    with given([*_given(), there_is_an_agent(), _agentbarn_telegram_connection()]) as context:
        with when("an OpenClaw Agent with Agent Barn Telegram starts"):
            started = _start(context)

        with then("OpenClaw calls the proxy with its stand-in token and listens for forwarded updates"):
            assert_that(started, equal_to(status.HTTP_200_OK))
            config_map, secret, ports = _created(context)
            telegram = json.loads(config_map["openclaw-config-overlay.json"])["channels"]["telegram"]
            assert_that(telegram["apiRoot"], equal_to(f"{_COMMUNICATIONS}/telegram/{context.connection.id}"))
            assert_that(telegram["webhookSecret"], equal_to("${AGENTBARN_TELEGRAM_WEBHOOK_SECRET}"))
            assert_that(telegram["groupPolicy"], equal_to("disabled"))
            assert_that(secret["TELEGRAM_BOT_TOKEN"], equal_to(runtime_api_token(_DRIVER_KEY, _REAL_TOKEN)))
            assert_that(secret["AGENTBARN_TELEGRAM_WEBHOOK_SECRET"], equal_to(runtime_webhook_secret(_DRIVER_KEY)))
            assert_that(secret["AGENTBARN_NATIVE_CHANNELS"].split(","), has_item("telegram"))
            assert_that(ports, has_item("tg-webhook"))

        with then("the shared bot's real token and the webhook secret stay out of the ConfigMap"):
            assert_that(json.dumps(secret), is_not(contains_string("the-real-shared-bot-token")))
            assert_that(json.dumps(config_map), is_not(contains_string("the-real-shared-bot-token")))
            assert_that(json.dumps(config_map), is_not(contains_string(runtime_webhook_secret(_DRIVER_KEY))))


def test_a_turned_off_connection_leaves_telegram_out() -> None:
    with given(
        [*_given(), there_is_an_agent(agent_type=AgentType.HERMES), _agentbarn_telegram_connection(enabled=False)]
    ) as context:
        with when("the Agent starts while its Agent Barn Telegram Connection is off"):
            _start(context)

        with then("Telegram is not configured and no webhook port is opened"):
            _, secret, ports = _created(context)
            assert_that("TELEGRAM_BOT_TOKEN" in secret, equal_to(False))
            assert_that(ports, is_not(has_item("tg-webhook")))


def test_without_the_shared_bot_an_existing_connection_is_left_out() -> None:
    with given([*_given(bot_configured=False), there_is_an_agent(), _agentbarn_telegram_connection()]) as context:
        with when("the Agent starts in an environment without the shared bot"):
            started = _start(context)

        with then("it starts without Telegram"):
            assert_that(started, equal_to(status.HTTP_200_OK))
            config_map, _, ports = _created(context)
            assert_that(
                "telegram" in json.loads(config_map["openclaw-config-overlay.json"]).get("channels", {}),
                equal_to(False),
            )
            assert_that(ports, is_not(has_item("tg-webhook")))


def test_agents_report_agentbarn_telegram_as_runtime_owned() -> None:
    # The dashboard restarts a running Agent after changing a runtime-owned Connection,
    # because the runtime reads those Connections only when it starts.
    with given([*_given(), there_is_an_agent()]) as context:
        response = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.json()["native_platform_keys"], has_item("agentbarn_telegram"))
