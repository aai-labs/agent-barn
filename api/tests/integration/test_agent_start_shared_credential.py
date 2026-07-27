from fastapi import status
from hamcrest import assert_that, contains_string, equal_to
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
    MockK8sModule,
    MockLiteLLMModule,
    TEST_ENCRYPTION_KEY,
    there_is_a_shared_credential,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_AGENTS = "/api/v1/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
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


def test_start_agent_with_shared_credential_sets_status_running():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_shared_credential()]) as ctx:
        client: TestClient = ctx.client
        k8s: KubernetesClient = ctx.injector.get(KubernetesClient)

        with when("I attach a shared jira credential and start the agent"):
            client.patch(
                f"{_AGENTS}/{ctx.agent.id}",
                json={
                    "shared_credentials": [{"shared_credential_id": str(ctx.shared_credential.id)}],
                },
                headers=_auth(ctx),
            )
            response = client.post(f"{_AGENTS}/{ctx.agent.id}/start", headers=_auth(ctx))

        with then("the agent starts and the jira profile is injected"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to(AgentStatus.RUNNING.value))
            config_map = k8s.create_config_map.call_args.args[1]
            agents_md = config_map.data["AGENTS.md"]
            assert_that(agents_md, contains_string("--profile jira-work"))
