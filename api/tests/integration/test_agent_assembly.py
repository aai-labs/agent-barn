import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.models import AgentType
from api.domains.agents.service import AgentService
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]


@pytest.mark.parametrize("agent_type", [AgentType.HERMES, AgentType.OPENCLAW])
def test_assembling_a_preflight_builds_the_resources_and_creates_nothing(agent_type):
    with given([*_GIVEN, there_is_an_agent(agent_type=agent_type)]) as context:
        assembled = context.injector.get(AgentService)._assemble_agent(context.agent, preflight=True)

        name = f"agent-{context.agent.id}"
        for resource in (assembled.secret, assembled.config_map, assembled.deployment, assembled.service):
            assert_that(resource.metadata.name, equal_to(name))
        k8s = context.injector.get(KubernetesClient)
        for method in ("create_secret", "create_config_map", "create_deployment", "create_service", "create_pvc"):
            assert_that(getattr(k8s, method).called, equal_to(False), method)
