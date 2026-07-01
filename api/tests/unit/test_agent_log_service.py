import datetime as dt
from unittest.mock import MagicMock

from hamcrest import assert_that, equal_to, has_length
from sqlmodel import Session

from api.domains.agents.models import AgentLogSnapshot, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization


def _build_user_context():
    def step(context):
        context.current_user_context = CurrentUserContext(
            user=context.user,
            organization_ids=[context.organization.id],
            user_organization_map={context.organization.id: context.organization_user},
            current_user_organization=context.organization_user,
        )

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
    _build_user_context(),
]


def _k8s(context) -> MagicMock:
    return context.injector.get(KubernetesClient)


# --- get_agent_logs ---


def test_get_agent_logs_returns_live_lines_when_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        service: AgentService = context.injector.get(AgentService)
        k8s = _k8s(context)
        k8s.read_pod_logs.return_value = "hello\nworld"

        with when("I get logs for a running agent"):
            result = service.get_agent_logs(
                context.agent.id, context.current_user_context
            )

            with then("live lines are returned"):
                assert_that(result.source, equal_to("live"))
                assert_that(result.lines, equal_to(["hello", "world"]))


def test_get_agent_logs_returns_snapshot_lines_when_stopped():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        service: AgentService = context.injector.get(AgentService)
        repo: AgentRepository = context.injector.get(AgentRepository)

        now = dt.datetime.now(dt.timezone.utc)
        repo.save_log_snapshot(
            AgentLogSnapshot(
                agent_id=context.agent.id,
                session_started_at=now,
                session_ended_at=now,
                log_text="saved\nlog\ndata",
                byte_size=14,
            )
        )

        with when("I get logs for a stopped agent"):
            result = service.get_agent_logs(
                context.agent.id, context.current_user_context
            )

            with then("snapshot lines are returned"):
                assert_that(result.source, equal_to("snapshot"))
                assert_that(result.lines, equal_to(["saved", "log", "data"]))


def test_get_agent_logs_returns_empty_when_no_snapshot():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        service: AgentService = context.injector.get(AgentService)

        with when("I get logs for a stopped agent with no snapshots"):
            result = service.get_agent_logs(
                context.agent.id, context.current_user_context
            )

            with then("empty snapshot result is returned"):
                assert_that(result.source, equal_to("snapshot"))
                assert_that(result.lines, has_length(0))


# --- _capture_logs_before_stop ---


def test_capture_logs_stores_snapshot():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        service: AgentService = context.injector.get(AgentService)
        repo: AgentRepository = context.injector.get(AgentRepository)
        k8s = _k8s(context)
        k8s.read_pod_logs.return_value = "line1\nline2\nline3"

        with when("logs are captured before stop"):
            service._capture_logs_before_stop(context.agent)

            with then("a snapshot is persisted"):
                snapshot = repo.get_latest_log_snapshot(context.agent.id)
                assert snapshot is not None
                assert_that(snapshot.log_text, equal_to("line1\nline2\nline3"))
                assert_that(snapshot.agent_id, equal_to(context.agent.id))


def test_capture_logs_truncates_over_1mb():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        service: AgentService = context.injector.get(AgentService)
        repo: AgentRepository = context.injector.get(AgentRepository)
        k8s = _k8s(context)
        big_text = "x" * (2 * 1_048_576)
        k8s.read_pod_logs.return_value = big_text

        with when("logs exceed 1MB"):
            service._capture_logs_before_stop(context.agent)

            with then("the snapshot is truncated to ~1MB"):
                snapshot = repo.get_latest_log_snapshot(context.agent.id)
                assert snapshot is not None
                assert snapshot.byte_size <= 1_048_576


def test_capture_logs_swallows_exceptions():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        service: AgentService = context.injector.get(AgentService)
        k8s = _k8s(context)
        k8s.read_pod_logs.side_effect = RuntimeError("k8s down")

        with when("log capture raises an exception"):
            service._capture_logs_before_stop(context.agent)

            with then("no exception propagates"):
                pass


_ = (Session, MockLiteLLMModule)
