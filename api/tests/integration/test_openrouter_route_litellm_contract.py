from unittest.mock import Mock
from uuid import uuid7

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.llm_providers import service as llm_provider_service
from api.domains.llm_providers.service import PlatformLlmProviderService
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.openrouter.client import OpenRouterClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.helpers.litellm_model_store import (
    MASTER_KEY,
    openrouter_stub_is_running,
    pinned_litellm_runs_the_repository_config,
    restart_litellm,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

pytestmark = pytest.mark.xdist_group("heavy_containers")

KEY_URL = "/api/v1/platform/settings/llm-providers/openrouter/key"
ENV_KEY = "sk-or-v1-environment-key-0e0e"
FIRST_KEY = "sk-or-v1-first-saved-key-a1a1"
SECOND_KEY = "sk-or-v1-second-saved-key-b2b2"
MODEL = "openrouter/openai/gpt-4o-mini"


def platform_admin(context):
    user_id = uuid7()
    there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
    there_is_an_access_token_for_user(user_id)(context)


def the_api_routes_through_the_pinned_litellm(monkeypatch):
    def step(context):
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        monkeypatch.setattr(context.injector.get(PlatformLlmProviderService), "litellm", client)
        monkeypatch.setattr(llm_provider_service, "OPENROUTER_ROUTE_API_BASE", context.openrouter_stub.url)
        context.injector.get(OpenRouterClient).check_key = Mock(return_value=True)

    return step


def _save(context, key: str) -> httpx.Response:
    return context.client.put(
        KEY_URL, headers={"Authorization": f"Bearer {context.access_token}"}, json={"api_key": key}
    )


def _key_openrouter_received(context) -> str:
    response = httpx.post(
        f"{context.litellm_url}/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
        timeout=30,
    )
    assert_that(response.status_code, equal_to(200), response.text)
    return context.openrouter_stub.keys[-1]


def test_the_saved_openrouter_key_outranks_the_environment_key_and_survives_a_litellm_restart(monkeypatch):
    with given(
        [
            set_env_variable(
                {"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "SKIP_SLACK_TOKEN_VALIDATION": "true"}
            ),
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            platform_admin,
            openrouter_stub_is_running(),
            pinned_litellm_runs_the_repository_config(openrouter_api_key=ENV_KEY),
            the_api_routes_through_the_pinned_litellm(monkeypatch),
        ]
    ) as context:
        with then("the environment key serves Agents until a key is saved"):
            assert_that(_key_openrouter_received(context), equal_to(ENV_KEY))

        with when("a Platform Administrator saves a key"):
            first = _save(context, FIRST_KEY)

        with then("Agents use it ahead of the environment key"):
            assert_that(first.status_code, equal_to(200), first.text)
            assert_that(_key_openrouter_received(context), equal_to(FIRST_KEY))

        with when("the key is replaced"):
            second = _save(context, SECOND_KEY)

        with then("Agents use the replacement at once"):
            assert_that(second.status_code, equal_to(200), second.text)
            assert_that(_key_openrouter_received(context), equal_to(SECOND_KEY))

        with when("LiteLLM restarts"):
            restart_litellm(context)

        with then("the saved route is still the one Agents use"):
            assert_that(_key_openrouter_received(context), equal_to(SECOND_KEY))

        with then("LiteLLM never reports a key back"):
            info = httpx.get(
                f"{context.litellm_url}/model/info", headers={"Authorization": f"Bearer {MASTER_KEY}"}, timeout=10
            )
            assert_that(info.status_code, equal_to(200), info.text)
            for key in (ENV_KEY, FIRST_KEY, SECOND_KEY):
                assert key not in info.text
