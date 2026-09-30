"""An Agent reaches memory through the proxy with a key only it holds (AF-338)."""

import json
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to, is_not, none, starts_with
from starlette.testclient import TestClient

from api.domains.agents.memory_access import AgentMemoryAccessService, MemoryAccessDenied, MemoryKeyRejected
from api.domains.agents.models import AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.memory_groups.models import MemoryGroup
from api.domains.memory_groups.repository import MemoryGroupRepository
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.kubernetes.client import KubernetesClient
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

_AGENTS = "/api/v1/organizations/{organization_id}/agents"
_PROXY = "http://memory-proxy.test:8003"


def _given(agent_type: AgentType) -> list:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "API_EXTERNAL_URL": "https://api.test.com",
                "HONCHO_ENABLED": "true",
                # Unreachable on purpose: setting deriver instructions is best effort.
                "HONCHO_BASE_URL": "http://127.0.0.1:9",
                "AGENT_MEMORY_PROXY_BASE_URL": _PROXY,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(agent_type=agent_type),
        _in_a_memory_group(),
    ]


def _in_a_memory_group():
    def step(context):
        group = context.injector.get(MemoryGroupRepository).save(
            MemoryGroup(organization_id=context.organization.id, name="Pool")
        )
        agents = context.injector.get(AgentRepository)
        context.agent.memory_group_id = group.id
        agents.save(context.agent)
        context.group = group

    return step


def _memory_config(k8s: MagicMock, agent_type: AgentType) -> tuple[str, str]:
    data = k8s.create_config_map.call_args.args[1].data
    if agent_type == AgentType.HERMES:
        honcho = json.loads(data["honcho.json"])
        return honcho["baseUrl"], honcho["apiKey"]
    plugin = json.loads(data["openclaw-config-overlay.json"])["plugins"]["entries"]["openclaw-honcho"]["config"]
    return plugin["baseUrl"], plugin["apiKey"]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


@pytest.mark.parametrize("agent_type", [AgentType.OPENCLAW, AgentType.HERMES])
def test_a_started_agent_reaches_its_pool_through_the_proxy_until_it_stops(agent_type):
    with given(_given(agent_type)) as ctx:
        client: TestClient = ctx.client
        k8s: MagicMock = ctx.injector.get(KubernetesClient)
        access = ctx.injector.get(AgentMemoryAccessService)

        with when("the agent starts"):
            started = client.post(f"{_AGENTS}/{ctx.agent.id}/start", headers=_auth(ctx))
            base_url, key = _memory_config(k8s, agent_type)

        with then("its runtime is given the proxy and a memory key, never a Honcho token"):
            assert_that(started.status_code, equal_to(200))
            assert_that(base_url, equal_to(_PROXY))
            assert_that(key, is_not(none()))
            assert_that(key.split(".", 1)[0], equal_to(str(ctx.agent.id)))  # names its Agent; not a JWT
            assert_that(access.authorize(key), equal_to(f"af-pool-{ctx.group.id}"))

        with when("the agent stops"):
            client.post(f"{_AGENTS}/{ctx.agent.id}/stop", headers=_auth(ctx))

        with then("the same key no longer reaches memory"):
            with pytest.raises(MemoryAccessDenied):
                access.authorize(key)


def test_a_restart_replaces_the_key():
    with given(_given(AgentType.OPENCLAW)) as ctx:
        client: TestClient = ctx.client
        k8s: MagicMock = ctx.injector.get(KubernetesClient)
        access = ctx.injector.get(AgentMemoryAccessService)

        client.post(f"{_AGENTS}/{ctx.agent.id}/start", headers=_auth(ctx))
        _, first = _memory_config(k8s, AgentType.OPENCLAW)
        client.post(f"{_AGENTS}/{ctx.agent.id}/stop", headers=_auth(ctx))
        client.post(f"{_AGENTS}/{ctx.agent.id}/start", headers=_auth(ctx))
        _, second = _memory_config(k8s, AgentType.OPENCLAW)

        assert_that(second, is_not(equal_to(first)))
        assert_that(access.authorize(second), starts_with("af-pool-"))
        with pytest.raises(MemoryKeyRejected):
            access.authorize(first)


def test_an_agent_started_during_a_suspension_gets_memory_back_when_it_lifts():
    """Starting during a suspension still issues the key and the memory config: the
    proxy refuses it while suspended and lets it through once the suspension lifts,
    without a restart — the same as an Agent that was already running."""
    with given(_given(AgentType.OPENCLAW)) as ctx:
        client: TestClient = ctx.client
        k8s: MagicMock = ctx.injector.get(KubernetesClient)
        access = ctx.injector.get(AgentMemoryAccessService)
        organizations = ctx.injector.get(OrganizationRepository)

        with when("the agent starts while its Organization's memory is suspended"):
            organization = organizations.get(ctx.organization.id)
            organization.llm_memory_suspended_key = organization.llm_budget_window_key
            organizations.save(organization)
            client.post(f"{_AGENTS}/{ctx.agent.id}/start", headers=_auth(ctx))
            base_url, key = _memory_config(k8s, AgentType.OPENCLAW)

        with then("it is given memory, but refused while suspended"):
            assert_that(base_url, equal_to(_PROXY))
            with pytest.raises(MemoryAccessDenied):
                access.authorize(key)

        with when("the suspension lifts"):
            organization = organizations.get(ctx.organization.id)
            organization.llm_memory_suspended_key = None
            organizations.save(organization)

        with then("the same running agent reaches its pool again"):
            assert_that(access.authorize(key), equal_to(f"af-pool-{ctx.group.id}"))
