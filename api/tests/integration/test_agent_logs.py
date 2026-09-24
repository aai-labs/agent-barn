from datetime import UTC, datetime

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.infrastructure.kubernetes.client import KubernetesClient
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
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
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


def test_get_agent_logs_requires_auth():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I request logs without auth"):
            response = client.get(f"{_BASE}/{context.agent.id}/logs")

            with then("401 is returned"):
                assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_logs_returns_404_for_nonexistent_agent():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "01961234-5678-7abc-def0-123456789abc"

        with when("I request logs for a nonexistent agent"):
            response = client.get(f"{_BASE}/{fake_id}/logs", headers=_auth(context))

            with then("404 is returned"):
                assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_stream_agent_logs_requires_auth():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I request log stream without auth"):
            response = client.get(f"{_BASE}/{context.agent.id}/logs/stream")

            with then("401 is returned"):
                assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_logs_returns_empty_snapshot_for_stopped_agent():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client

        with when("I request logs for a stopped agent with no snapshots"):
            response = client.get(f"{_BASE}/{context.agent.id}/logs", headers=_auth(context))

            with then("empty snapshot result is returned"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["source"], equal_to("snapshot"))
                assert_that(body["lines"], has_length(0))


def test_runtime_diagnostics_returns_previous_container_logs():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        context.injector.get(KubernetesClient).get_runtime_diagnostics.return_value = {
            "observed_at": datetime.now(UTC),
            "available": True,
            "restart_count": 21,
            "waiting_reason": "CrashLoopBackOff",
            "exit_code": 1,
            "previous_logs": ["Legacy workspace setup state requires migration"],
            "previous_logs_available": True,
        }
        response = context.client.get(f"{_BASE}/{context.agent.id}/diagnostics", headers=_auth(context))
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["restart_count"], equal_to(21))
        assert_that(response.json()["previous_logs"], equal_to(["Legacy workspace setup state requires migration"]))


def test_runtime_diagnostics_cluster_errors_are_safe():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        context.injector.get(KubernetesClient).get_runtime_diagnostics.side_effect = RuntimeError(
            "private-cluster-detail"
        )
        response = context.client.get(f"{_BASE}/{context.agent.id}/diagnostics", headers=_auth(context))
        assert_that(response.status_code, equal_to(503))
        assert_that(response.json()["detail"], equal_to("Runtime diagnostics are temporarily unavailable"))


def test_stopped_runtime_diagnostics_reports_no_current_evidence():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        response = context.client.get(f"{_BASE}/{context.agent.id}/diagnostics", headers=_auth(context))
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["available"], equal_to(False))


def test_runtime_diagnostics_requires_authentication():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        response = context.client.get(f"{_BASE}/{context.agent.id}/diagnostics")
        assert_that(response.status_code, equal_to(401))
