import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, equal_to, has_length

from api.core.config import Config
from api.domains.agents.models import AgentStatus
from api.domains.agents.service import AgentService
from api.infrastructure.kubernetes import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_IMAGE": "registry.example.com/agentbarn-api:test",
            "RESTORE_POINT_MAX_PER_AGENT": "2",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _managed_url(context) -> str:
    return f"{_BASE}/{context.agent.id}/managed-update"


def test_wait_for_ready_returns_true_when_the_pod_reports_ready():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("ready", None)

        with when("the newest pod is ready"):
            healthy = service._wait_for_ready(context.agent.id, 10, poll_seconds=0)

        with then("the update may proceed, after a single read"):
            assert_that(healthy, equal_to(True))
            assert_that(k8s.get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_returns_false_immediately_when_the_pod_crashed():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("crashed", "BackOff")

        with when("the new pod crash-loops"):
            healthy = service._wait_for_ready(context.agent.id, 60, poll_seconds=0)

        with then("the wait gives up at once rather than burning the timeout"):
            assert_that(healthy, equal_to(False))
            assert_that(k8s.get_pod_readiness.call_count, equal_to(1))


def test_wait_for_ready_gives_up_after_the_timeout():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        k8s.get_pod_readiness.return_value = ("initializing", None)

        with when("the pod stays initializing past the timeout"):
            healthy = service._wait_for_ready(context.agent.id, 1, poll_seconds=0)

        with then("the wait reports the update as unhealthy"):
            assert_that(healthy, equal_to(False))
            assert_that(k8s.get_pod_readiness.call_count > 1, equal_to(True))


def test_teardown_workload_deletes_only_the_deployment():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        service = context.injector.get(AgentService)
        k8s = context.injector.get(KubernetesClient)
        namespace = context.injector.get(Config).k8s_namespace

        with when("the failed update's workload is torn down"):
            service._teardown_workload(context.agent.id)

        with then("the PVC is freed, and nothing else is touched"):
            k8s.delete_deployment.assert_called_once_with(f"agent-{context.agent.id}", namespace)
            assert_that(k8s.delete_config_map.called, equal_to(False))
            assert_that(k8s.delete_secret.called, equal_to(False))
