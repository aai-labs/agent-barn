from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, none, not_none
from prometheus_client import REGISTRY
from sqlmodel import create_engine

from api.core.metrics import (
    PROBE_REGISTRY,
    clear_openrouter_credits_cache,
    refresh_agents_in_error,
    refresh_database_gauge,
    refresh_openrouter_credits,
    render_metrics,
)
from api.domains.agents.models import Agent, AgentPlatform, AgentStatus, AgentType
from api.domains.ingest.models import IngestBatchRequest, IngestToolResultEvent
from api.domains.ingest.service import IngestService
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.tests.core.givenpy import given, then, when


@pytest.fixture(autouse=True)
def _clear_openrouter_credits_cache():
    clear_openrouter_credits_cache()
    yield
    clear_openrouter_credits_cache()


def _make_agent() -> Agent:
    return Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="test-agent",
        status=AgentStatus.RUNNING,
        platform=AgentPlatform.SLACK,
        agent_type=AgentType.OPENCLAW,
        litellm_key_encrypted="encrypted",
        model="gpt-5",
        template_slug="test",
        template_version=1,
        ingest_key_encrypted="encrypted-key",
    )


def _make_tool_call(agent: Agent, tool_name: str, status: ToolCallStatus) -> ToolCall:
    now = datetime.now(timezone.utc)
    return ToolCall(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        session_id="session-abc",
        external_id="tc-1",
        tool_name=tool_name,
        arguments={},
        status=status,
        occurred_at=now,
    )


def _make_service(tc_repo) -> IngestService:
    return IngestService(
        agent_repository=MagicMock(),
        conversation_repository=MagicMock(),
        tool_call_repository=tc_repo,
    )


def _tool_calls_total(tool_name: str, status: str) -> float | None:
    return REGISTRY.get_sample_value("agentfarm_tool_calls_total", {"tool_name": tool_name, "status": status})


def _mock_tc_repo(completed: ToolCall | None) -> MagicMock:
    tc_repo = MagicMock()
    session = MagicMock()
    tc_repo.get_session.return_value.__enter__ = MagicMock(return_value=session)
    tc_repo.get_session.return_value.__exit__ = MagicMock(return_value=False)
    tc_repo.complete.return_value = completed
    return tc_repo


def _result_batch() -> IngestBatchRequest:
    return IngestBatchRequest(
        tool_results=[
            IngestToolResultEvent(
                external_id="tc-1",
                result="boom",
                is_error=True,
                completed_at=datetime.now(timezone.utc),
            )
        ]
    )


# --- tool call counter ---


def test_tool_call_counter_increments_on_error_result():
    with given():
        agent = _make_agent()
        row = _make_tool_call(agent, "unit-error-tool", ToolCallStatus.ERROR)
        service = _make_service(_mock_tc_repo(completed=row))
        before = _tool_calls_total("unit-error-tool", "error") or 0.0

        with when("I process a failing tool result"):
            service.process(agent, _result_batch())

        with then("the error counter increments with the tool name label"):
            assert_that(_tool_calls_total("unit-error-tool", "error"), equal_to(before + 1.0))


def test_tool_call_counter_increments_on_success_result():
    with given():
        agent = _make_agent()
        row = _make_tool_call(agent, "unit-success-tool", ToolCallStatus.SUCCESS)
        service = _make_service(_mock_tc_repo(completed=row))
        before = _tool_calls_total("unit-success-tool", "success") or 0.0

        with when("I process a successful tool result"):
            service.process(agent, _result_batch())

        with then("the success counter increments"):
            assert_that(
                _tool_calls_total("unit-success-tool", "success"),
                equal_to(before + 1.0),
            )


def test_tool_call_counter_not_incremented_when_no_row_matched():
    with given():
        agent = _make_agent()
        service = _make_service(_mock_tc_repo(completed=None))

        with when("I process a tool result that matches no pending row"):
            service.process(agent, _result_batch())

        with then("no counter series is created for it"):
            assert_that(_tool_calls_total("nonexistent-tool", "error"), none())


# --- database probe ---


def test_refresh_database_gauge_sets_one_when_reachable():
    with given():
        engine = create_engine("sqlite://")

        with when("I refresh the database gauge"):
            refresh_database_gauge(engine)

        with then("the gauge reads 1"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_database_up"),
                equal_to(1.0),
            )


def test_refresh_database_gauge_sets_zero_without_raising_on_failure():
    with given():
        broken_engine = create_engine("sqlite:////nonexistent-dir/agentfarm.db")

        with when("I refresh the gauge against a broken engine"):
            refresh_database_gauge(broken_engine)

        with then("the gauge reads 0 and nothing raises"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_database_up"),
                equal_to(0.0),
            )


# --- agents-in-error probe ---


def test_refresh_agents_in_error_sets_count():
    with given():
        with when("I refresh with a count of 3"):
            refresh_agents_in_error(lambda: 3)

        with then("the gauge reads 3"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_agents_in_error"),
                equal_to(3.0),
            )


def test_refresh_agents_in_error_keeps_last_value_on_failure():
    with given():
        refresh_agents_in_error(lambda: 2)

        def boom() -> int:
            raise RuntimeError("db down")

        with when("the count callable raises"):
            refresh_agents_in_error(boom)

        with then("the gauge keeps its last value and nothing raises"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_agents_in_error"),
                equal_to(2.0),
            )


# --- openrouter credits probe ---


def _config(api_key: str = "sk-test", ttl: int = 300) -> MagicMock:
    return MagicMock(
        openrouter_api_key=api_key,
        openrouter_base_url="https://openrouter.test/api/v1",
        openrouter_credits_cache_ttl_seconds=ttl,
    )


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_sets_key_limit_remaining(mock_config, mock_get):
    with given():
        mock_config.return_value = _config()
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"limit_remaining": 75.0}}
        mock_get.return_value = response

        with when("I refresh the credits gauge"):
            refresh_openrouter_credits()

        with then("the key's remaining credit limit and scrape_ok are set"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_remaining"),
                equal_to(75.0),
            )
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_scrape_ok"),
                equal_to(1.0),
            )


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_unlimited_key_reads_infinite(mock_config, mock_get):
    with given():
        mock_config.return_value = _config()
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"limit_remaining": None}}
        mock_get.return_value = response

        with when("I refresh against a key with no credit limit"):
            refresh_openrouter_credits()

        with then("the gauge reads +Inf and the poll counts as healthy"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_remaining"),
                equal_to(float("inf")),
            )
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_scrape_ok"),
                equal_to(1.0),
            )


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_polls_key_endpoint_with_inference_key(mock_config, mock_get):
    with given():
        mock_config.return_value = _config(api_key="sk-inference")
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"limit_remaining": 1.0}}
        mock_get.return_value = response

        with when("I refresh the credits gauge"):
            refresh_openrouter_credits()

        with then("it calls GET /key with the inference key"):
            assert_that(
                mock_get.call_args.args[0],
                equal_to("https://openrouter.test/api/v1/key"),
            )
            assert_that(
                mock_get.call_args.kwargs["headers"]["Authorization"],
                equal_to("Bearer sk-inference"),
            )


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_scrape_not_ok_without_key(mock_config, mock_get):
    with given():
        mock_config.return_value = _config(api_key="")

        with when("I refresh with no OpenRouter API key configured"):
            refresh_openrouter_credits()

        with then("scrape_ok is 0 and no request is made"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_scrape_ok"),
                equal_to(0.0),
            )
            mock_get.assert_not_called()


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_scrape_not_ok_on_http_error(mock_config, mock_get):
    with given():
        mock_config.return_value = _config()
        mock_get.side_effect = RuntimeError("connection refused")

        with when("I refresh and the request fails"):
            refresh_openrouter_credits()

        with then("scrape_ok is 0 and nothing raises"):
            assert_that(
                PROBE_REGISTRY.get_sample_value("agentfarm_openrouter_credits_scrape_ok"),
                equal_to(0.0),
            )


@patch("api.core.metrics.httpx.get")
@patch("api.core.metrics.get_config")
def test_refresh_openrouter_credits_respects_ttl_cache(mock_config, mock_get):
    with given():
        mock_config.return_value = _config(ttl=300)
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"limit_remaining": 10}}
        mock_get.return_value = response

        with when("I refresh twice within the TTL"):
            refresh_openrouter_credits()
            refresh_openrouter_credits()

        with then("only one HTTP request is made"):
            assert_that(mock_get.call_count, equal_to(1))


# --- rendering ---


def test_render_metrics_concatenates_registries():
    with given():
        refresh_agents_in_error(lambda: 0)

        with when("I render the default and probe registries"):
            output = render_metrics(REGISTRY, PROBE_REGISTRY).decode()

        with then("it contains metrics from both"):
            assert_that(output, contains_string("agentfarm_agents_in_error"))
            assert_that(output, not_none())
