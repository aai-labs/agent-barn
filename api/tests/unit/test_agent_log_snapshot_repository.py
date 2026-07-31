import datetime as dt
from uuid import UUID

from hamcrest import assert_that, equal_to, none, not_none
from sqlmodel import Session

from api.domains.agents.models import AgentLogSnapshot
from api.domains.agents.repository import AgentRepository
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

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _make_snapshot(
    agent_id: UUID,
    log_text: str = "line1\nline2\n",
    session_started_at: dt.datetime | None = None,
    session_ended_at: dt.datetime | None = None,
) -> AgentLogSnapshot:
    now = _now()
    return AgentLogSnapshot(
        agent_id=agent_id,
        session_started_at=session_started_at or now,
        session_ended_at=session_ended_at or now,
        log_text=log_text,
        byte_size=len(log_text.encode("utf-8")),
    )


def test_save_log_snapshot_persists():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repo: AgentRepository = context.injector.get(AgentRepository)

        with when("I save a log snapshot"):
            snapshot = _make_snapshot(context.agent.id)
            result = repo.save_log_snapshot(snapshot)

            with then("it is persisted with an id"):
                assert_that(result.id, not_none())
                assert_that(result.agent_id, equal_to(context.agent.id))
                assert_that(result.log_text, equal_to("line1\nline2\n"))


def test_get_latest_log_snapshot_returns_most_recent():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repo: AgentRepository = context.injector.get(AgentRepository)
        agent_id = context.agent.id

        t1 = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
        t2 = dt.datetime(2026, 6, 10, tzinfo=dt.UTC)
        t3 = dt.datetime(2026, 6, 20, tzinfo=dt.UTC)

        repo.save_log_snapshot(_make_snapshot(agent_id, "old", session_ended_at=t1))
        repo.save_log_snapshot(_make_snapshot(agent_id, "middle", session_ended_at=t2))
        repo.save_log_snapshot(_make_snapshot(agent_id, "newest", session_ended_at=t3))

        with when("I get the latest log snapshot"):
            result = repo.get_latest_log_snapshot(agent_id)

            with then("the most recently ended session is returned"):
                assert_that(result, not_none())
                assert result is not None
                assert_that(result.log_text, equal_to("newest"))


def test_get_latest_log_snapshot_returns_none_when_empty():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repo: AgentRepository = context.injector.get(AgentRepository)

        with when("I get the latest log snapshot for an agent with none"):
            result = repo.get_latest_log_snapshot(context.agent.id)

            with then("None is returned"):
                assert_that(result, none())


_ = (Session, MockLiteLLMModule)
