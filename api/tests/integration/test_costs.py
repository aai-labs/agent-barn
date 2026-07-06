import hashlib

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.infrastructure.litellm.client import LiteLLMClient
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
from api.tests.steps.template import there_is_a_template

_BASE = "/api/v1/costs"

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
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
    there_is_an_agent(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def test_get_costs_summary_returns_200_and_data():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)

        key_hash = hashlib.sha256(FAKE_LITELLM_KEY.encode()).hexdigest()

        litellm.get_global_spend_report.return_value = {
            key_hash: {
                "spend": 10.5,
                "total_input_tokens": 100,
                "total_output_tokens": 50,
                "models": {
                    "gpt-4": {
                        "spend": 10.5,
                        "total_input_tokens": 100,
                        "total_output_tokens": 50,
                    }
                },
            }
        }

        with when("I request the costs summary"):
            response = client.get(f"{_BASE}/summary", headers=_auth(context))

        with then("it returns 200 with the correct aggregation"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["totalCost"], equal_to(10.5))
            assert_that(data["agents"], has_length(1))
            assert_that(data["agents"][0]["total_cost"], equal_to(10.5))
            assert_that(data["agents"][0]["prompt_tokens"], equal_to(100))
            assert_that(data["byModel"], has_length(1))


def test_get_agent_cost_returns_200_and_data():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        litellm: LiteLLMClient = context.injector.get(LiteLLMClient)
        agent_id = str(context.agent.id)

        litellm.get_key_info.return_value = {
            "spend": 5.0,
        }

        with when("I request the individual agent cost"):
            response = client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("it returns 200 with the agent's cost"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["total_cost"], equal_to(5.0))
            assert_that(data["agent_id"], equal_to(agent_id))


def test_get_costs_summary_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I request costs summary without auth"):
            response = client.get(f"{_BASE}/summary")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I request agent cost without auth"):
            response = client.get(f"{_BASE}/agents/{agent_id}")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "11111111-1111-1111-1111-111111111111"

        with when("I request an agent that does not exist"):
            response = client.get(f"{_BASE}/agents/{fake_id}", headers=_auth(context))

        with then("it returns 404 Not Found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
