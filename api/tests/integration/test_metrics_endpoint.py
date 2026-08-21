from datetime import UTC, datetime

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to
from starlette.testclient import TestClient

from api.api_app import create_app
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.infrastructure.crypto import encrypt_token
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_ingest_server,
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

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            # Keep the credits probe offline: a developer's real key in the
            # environment would otherwise make /metrics call OpenRouter.
            "OPENROUTER_API_KEY": "",
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


def _set_ingest_key(key="test-ingest-key-abc"):
    def step(context):
        repo: AgentRepository = context.injector.get(AgentRepository)
        agent = repo.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        repo.save(agent)
        context.agent = agent
        context.ingest_key = key

    return step


def _mark_agent_errored():
    def step(context):
        repo: AgentRepository = context.injector.get(AgentRepository)
        agent = repo.get_by_id(context.agent.id)
        assert agent is not None
        agent.status = AgentStatus.ERROR
        repo.save(agent)

    return step


def test_metrics_exposes_http_metrics_and_database_gauge():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I make an API request and then scrape /metrics"):
            client.get("/api/v1/health")
            response = client.get("/metrics")

        with then("it returns HTTP metrics and the database gauge"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.text, contains_string("http_requests_total"))
            assert_that(response.text, contains_string("agentbarn_database_up 1.0"))


def test_metrics_reports_agents_in_error():
    with given([*_GIVEN, there_is_an_agent(), _mark_agent_errored()]) as context:
        client: TestClient = context.client

        with when("I scrape /metrics with one agent in ERROR"):
            response = client.get("/metrics")

        with then("the agents-in-error gauge reads 1"):
            assert_that(response.text, contains_string("agentbarn_agents_in_error 1.0"))


def test_metrics_reports_openrouter_scrape_not_ok_without_key():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I scrape /metrics without an OpenRouter API key"):
            response = client.get("/metrics")

        with then("the credits scrape_ok gauge reads 0"):
            assert_that(
                response.text,
                contains_string("agentbarn_openrouter_credits_scrape_ok 0.0"),
            )


def test_ingest_metrics_counts_tool_call_errors():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            _set_ingest_key(),
            prepare_ingest_server(),
        ]
    ) as context:
        now = datetime.now(UTC).isoformat()
        payload = {
            "tool_calls": [
                {
                    "external_id": "tc-metrics-1",
                    "session_id": "session-metrics",
                    "tool_name": "metrics-probe-tool",
                    "arguments": {},
                    "occurred_at": now,
                }
            ],
            "tool_results": [
                {
                    "external_id": "tc-metrics-1",
                    "result": "boom",
                    "is_error": True,
                    "completed_at": now,
                }
            ],
        }

        with when("I ingest a failing tool call and scrape the ingest /metrics"):
            ingest_response = context.ingest_client.post(
                f"/ingest/v1/agents/{context.agent.id}/events",
                json=payload,
                headers={"Authorization": f"Bearer {context.ingest_key}"},
            )
            response = context.ingest_client.get("/metrics")

        with then("the tool-call error counter is exposed with the tool label"):
            assert_that(ingest_response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(response.status_code, equal_to(200))
            body = response.text
            line = next(
                (
                    ln
                    for ln in body.splitlines()
                    if ln.startswith("agentbarn_tool_calls_total")
                    and 'tool_name="metrics-probe-tool"' in ln
                    and 'status="error"' in ln
                ),
                None,
            )
            assert line is not None, "tool-call error series not found in /metrics"
            assert_that(line.rsplit(" ", 1)[-1], equal_to("1.0"))


def test_creating_the_app_twice_does_not_break_metrics():
    with given(_GIVEN) as context:
        with when("I create a second app in the same process"):
            second_app = create_app(injector=context.injector)
            second_client = TestClient(second_app)
            response = second_client.get("/metrics")

        with then("its /metrics still works"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.text, contains_string("agentbarn_database_up"))
