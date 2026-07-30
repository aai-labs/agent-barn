import datetime
from uuid import UUID

from hamcrest import assert_that, equal_to, has_length, is_, is_not, none
from sqlmodel import Session

from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.models import (
    ToolCall,
    ToolCallFilter,
    ToolCallStatus,
)
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.shared.models import Pagination
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.core.modules import set_env_variable


_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
]


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _find_by_agent(
    repository: ToolCallRepository,
    context,
    agent_id: UUID,
    tool_call_filter: ToolCallFilter,
    pagination: Pagination,
):
    return repository.find_by_agent(
        agent_id,
        tool_call_filter,
        pagination,
        AuthorizationScope(organization_id=context.organization.id),
    )


def _seed_pending(
    repo: ToolCallRepository,
    *,
    organization_id: UUID,
    agent_id: UUID,
    external_id: str,
    tool_name: str = "read",
    session_id: str = "session-1",
    arguments: dict | None = None,
    occurred_at: datetime.datetime | None = None,
) -> None:
    with repo.get_session() as session:
        repo.upsert_pending(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            session_id=session_id,
            external_id=external_id,
            tool_name=tool_name,
            arguments=arguments or {"path": "/tmp/x"},
            occurred_at=occurred_at or _now(),
        )
        session.commit()


def _complete(
    repo: ToolCallRepository,
    *,
    agent_id: UUID,
    external_id: str,
    result: dict | None = None,
    is_error: bool = False,
    completed_at: datetime.datetime | None = None,
) -> ToolCall | None:
    with repo.get_session() as session:
        row = repo.complete(
            session,
            agent_id=agent_id,
            external_id=external_id,
            result=result or {"output": "ok"},
            is_error=is_error,
            completed_at=completed_at or _now(),
        )
        session.commit()
        return row


def test_find_by_agent_returns_empty_when_no_rows():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)

        with when("I list tool calls for an agent with none recorded"):
            result = _find_by_agent(
                repository,
                context,
                context.agent.id,
                ToolCallFilter(),
                Pagination(page=1, size=20),
            )

            with then("an empty page is returned"):
                assert_that(result.items, has_length(0))
                assert_that(result.total, equal_to(0))


def test_upsert_pending_inserts_row():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)

        with when("I upsert a pending tool call"):
            _seed_pending(
                repository,
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                external_id="call_abc",
                tool_name="read",
            )

            with then("it appears in find_by_agent with PENDING status"):
                page = _find_by_agent(
                    repository,
                    context,
                    context.agent.id,
                    ToolCallFilter(),
                    Pagination(page=1, size=20),
                )
                assert_that(page.items, has_length(1))
                assert_that(page.items[0].status, equal_to(ToolCallStatus.PENDING))
                assert_that(page.items[0].tool_name, equal_to("read"))
                assert_that(page.items[0].result, is_(none()))
                assert_that(page.items[0].duration_ms, is_(none()))


def test_upsert_pending_is_idempotent_on_external_id_conflict():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)

        with when("I upsert the same external_id twice"):
            _seed_pending(
                repository,
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                external_id="call_same",
                tool_name="read",
            )
            _seed_pending(
                repository,
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                external_id="call_same",
                tool_name="ignored-on-conflict",
                arguments={"different": "args"},
            )

            with then("only one row exists"):
                page = _find_by_agent(
                    repository,
                    context,
                    context.agent.id,
                    ToolCallFilter(),
                    Pagination(page=1, size=20),
                )
                assert_that(page.items, has_length(1))
                assert_that(page.total, equal_to(1))
                assert_that(page.items[0].tool_name, equal_to("read"))


def test_complete_transitions_pending_to_success():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        start = _now()
        end = start + datetime.timedelta(milliseconds=250)

        _seed_pending(
            repository,
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            external_id="call_success",
            occurred_at=start,
        )

        with when("I complete it with isError=false"):
            ok = _complete(
                repository,
                agent_id=context.agent.id,
                external_id="call_success",
                result={"output": "done"},
                is_error=False,
                completed_at=end,
            )

            with then("status is SUCCESS, result is set, duration computed"):
                assert_that(ok, is_not(none()))
                page = _find_by_agent(
                    repository,
                    context,
                    context.agent.id,
                    ToolCallFilter(),
                    Pagination(page=1, size=20),
                )
                assert_that(page.items, has_length(1))
                row = page.items[0]
                assert_that(row.status, equal_to(ToolCallStatus.SUCCESS))
                assert_that(row.result, equal_to({"output": "done"}))
                assert_that(row.completed_at, is_not(none()))
                assert_that(row.duration_ms, equal_to(250))


def test_complete_transitions_pending_to_error():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)

        _seed_pending(
            repository,
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            external_id="call_error",
        )

        with when("I complete it with isError=true"):
            ok = _complete(
                repository,
                agent_id=context.agent.id,
                external_id="call_error",
                result={"error": "boom"},
                is_error=True,
            )

            with then("status is ERROR"):
                assert_that(ok, is_not(none()))
                page = _find_by_agent(
                    repository,
                    context,
                    context.agent.id,
                    ToolCallFilter(),
                    Pagination(page=1, size=20),
                )
                assert_that(page.items[0].status, equal_to(ToolCallStatus.ERROR))


def test_complete_returns_none_when_no_match():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)

        with when("I try to complete an external_id that doesn't exist"):
            ok = _complete(
                repository,
                agent_id=context.agent.id,
                external_id="never_seen",
            )

            with then("None is returned and no row is created"):
                assert_that(ok, is_(none()))
                page = _find_by_agent(
                    repository,
                    context,
                    context.agent.id,
                    ToolCallFilter(),
                    Pagination(page=1, size=20),
                )
                assert_that(page.items, has_length(0))


def test_filter_by_tool_name_uses_ilike():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        org_id = context.organization.id
        agent_id = context.agent.id

        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c1",
            tool_name="read",
        )
        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c2",
            tool_name="write",
        )
        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c3",
            tool_name="exec",
        )

        with when("I filter by partial tool name"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(tool_name="re"),
                Pagination(page=1, size=20),
            )

            with then("only matching rows return"):
                assert_that(page.items, has_length(1))
                assert_that(page.items[0].tool_name, equal_to("read"))


def test_filter_by_status():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        org_id = context.organization.id
        agent_id = context.agent.id

        _seed_pending(repository, organization_id=org_id, agent_id=agent_id, external_id="c1")
        _seed_pending(repository, organization_id=org_id, agent_id=agent_id, external_id="c2")
        _complete(repository, agent_id=agent_id, external_id="c2", is_error=False)
        _seed_pending(repository, organization_id=org_id, agent_id=agent_id, external_id="c3")
        _complete(repository, agent_id=agent_id, external_id="c3", is_error=True)

        with when("I filter by status=SUCCESS"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(status=ToolCallStatus.SUCCESS),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(1))
            assert_that(page.items[0].status, equal_to(ToolCallStatus.SUCCESS))

        with when("I filter by status=ERROR"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(status=ToolCallStatus.ERROR),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(1))
            assert_that(page.items[0].status, equal_to(ToolCallStatus.ERROR))

        with when("I filter by status=PENDING"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(status=ToolCallStatus.PENDING),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(1))
            assert_that(page.items[0].status, equal_to(ToolCallStatus.PENDING))


def test_filter_by_date_range():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        org_id = context.organization.id
        agent_id = context.agent.id

        t1 = datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc)
        t2 = datetime.datetime(2026, 5, 10, tzinfo=datetime.timezone.utc)
        t3 = datetime.datetime(2026, 5, 20, tzinfo=datetime.timezone.utc)

        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c1",
            occurred_at=t1,
        )
        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c2",
            occurred_at=t2,
        )
        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="c3",
            occurred_at=t3,
        )

        with when("I filter by from_date=t2"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(from_date=t2),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(2))

        with when("I filter by to_date=t3 (exclusive)"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(to_date=t3),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(2))

        with when("I filter by both from and to (t2 inclusive, t3 exclusive)"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(from_date=t2, to_date=t3),
                Pagination(page=1, size=20),
            )
            assert_that(page.items, has_length(1))
            assert_that(page.items[0].occurred_at, equal_to(t2))


def test_pagination_returns_correct_page_and_total():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        org_id = context.organization.id
        agent_id = context.agent.id

        for i in range(5):
            _seed_pending(
                repository,
                organization_id=org_id,
                agent_id=agent_id,
                external_id=f"c{i}",
                occurred_at=datetime.datetime(2026, 5, 1 + i, tzinfo=datetime.timezone.utc),
            )

        with when("I request page 1, size 2"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(),
                Pagination(page=1, size=2),
            )
            assert_that(page.items, has_length(2))
            assert_that(page.total, equal_to(5))
            assert_that(page.page, equal_to(1))
            assert_that(page.page_size, equal_to(2))

        with when("I request page 3, size 2"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(),
                Pagination(page=3, size=2),
            )
            assert_that(page.items, has_length(1))
            assert_that(page.total, equal_to(5))


def test_results_ordered_by_occurred_at_desc():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        org_id = context.organization.id
        agent_id = context.agent.id

        t_old = datetime.datetime(2026, 5, 1, tzinfo=datetime.timezone.utc)
        t_new = datetime.datetime(2026, 5, 20, tzinfo=datetime.timezone.utc)

        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="old",
            occurred_at=t_old,
        )
        _seed_pending(
            repository,
            organization_id=org_id,
            agent_id=agent_id,
            external_id="new",
            occurred_at=t_new,
        )

        with when("I list tool calls"):
            page = _find_by_agent(
                repository,
                context,
                agent_id,
                ToolCallFilter(),
                Pagination(page=1, size=20),
            )

            with then("newest comes first"):
                assert_that(page.items[0].occurred_at, equal_to(t_new))
                assert_that(page.items[1].occurred_at, equal_to(t_old))


def test_find_by_agent_is_scoped_to_agent():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(name="A"),
        ]
    ) as context:
        repository: ToolCallRepository = context.injector.get(ToolCallRepository)
        agent_a_id = context.agent.id
        org_id = context.organization.id

        # Create a second agent in same org
        there_is_an_agent(name="B")(context)
        agent_b_id = context.agent.id

        _seed_pending(repository, organization_id=org_id, agent_id=agent_a_id, external_id="for_a")
        _seed_pending(repository, organization_id=org_id, agent_id=agent_b_id, external_id="for_b")

        with when("I list for agent A"):
            page_a = _find_by_agent(
                repository,
                context,
                agent_a_id,
                ToolCallFilter(),
                Pagination(page=1, size=20),
            )

        with when("I list for agent B"):
            page_b = _find_by_agent(
                repository,
                context,
                agent_b_id,
                ToolCallFilter(),
                Pagination(page=1, size=20),
            )

            with then("each agent sees only its own tool calls"):
                assert_that(page_a.items, has_length(1))
                assert_that(page_b.items, has_length(1))


# Suppress unused-import lint; symbols below are used indirectly via the
# injector / sqlmodel registry.
_ = (Session, ToolCall, MockLiteLLMModule)
