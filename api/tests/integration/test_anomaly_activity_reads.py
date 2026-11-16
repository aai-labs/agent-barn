"""The activity reads anomaly detection takes from other domains (AF-453).

Each domain hands out its own figures through its service: hourly tool calls and
errors, tool calls stored since a cursor (with only the argument keys asked for),
hourly LLM calls and tokens, hourly writes, and Business Actions stored since a cursor.
These are background reads for the scheduled check, so they take an Agent id and no
caller.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from hamcrest import assert_that, contains_exactly, equal_to, has_properties
from sqlmodel import Session

from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.business_value.service import BusinessValueService
from api.domains.costs.models import CostRecord, CostSyncState
from api.domains.costs.service import CostService
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.domains.tool_calls.service import ToolCallService
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.cost import cost_records_are_clean
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

HOUR = datetime(2026, 11, 10, 9, tzinfo=UTC)

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
    there_is_an_organization(),
    there_is_an_agent_in_another_org(),
    there_is_an_agent(),
]


def _save(context, *rows) -> None:
    """In the order given: a Business Action's tool call has to be stored before it."""
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        for row in rows:
            session.add(row)
            session.flush()
        session.commit()


def _tool_call(
    agent,
    *,
    at: datetime,
    tool_name: str = "web_fetch",
    arguments: dict[str, Any] | None = None,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
    created_at: datetime | None = None,
) -> ToolCall:
    row = ToolCall(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        session_id="s",
        external_id=f"tc-{uuid4().hex}",
        tool_name=tool_name,
        arguments=arguments or {},
        status=status,
        occurred_at=at,
    )
    if created_at is not None:
        row.created_at = created_at
    return row


def _cost(agent, *, at: datetime, tokens: int = 100, is_memory: bool = False) -> CostRecord:
    return CostRecord(
        request_id=f"req-{uuid4().hex}",
        litellm_key_hash="hash",
        occurred_at=at,
        spend=Decimal("0.01"),
        total_tokens=tokens,
        model="m",
        status="success",
        agent_id=agent.id,
        organization_id=agent.organization_id,
        is_memory=is_memory,
    )


def _action(
    context, agent, *, at: datetime, integration: str, verb: str, is_write: bool | None, created_at=None
) -> tuple:
    tool_call = _tool_call(agent, at=at, tool_name="terminal", created_at=created_at)
    action = BusinessAction(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        tool_call_id=tool_call.id,
        ordinal=0,
        integration=integration,
        resource="records",
        verb=verb,
        is_write=is_write,
        status=BusinessActionStatus.SUCCESS,
        occurred_at=at,
        completed_at=at,
    )
    if created_at is not None:
        action.created_at = created_at
    return tool_call, action


def test_tool_calls_and_errors_are_counted_per_hour_for_one_agent():
    with given(_GIVEN) as context:
        agent = context.agent
        _save(
            context,
            _tool_call(agent, at=HOUR + timedelta(minutes=5)),
            _tool_call(agent, at=HOUR + timedelta(minutes=50), status=ToolCallStatus.ERROR),
            _tool_call(agent, at=HOUR + timedelta(hours=1, minutes=1)),
            _tool_call(agent, at=HOUR - timedelta(minutes=1)),
            _tool_call(context.other_org_agent, at=HOUR + timedelta(minutes=5)),
        )

        hours = context.injector.get(ToolCallService).hourly_tool_activity(agent.id, HOUR, HOUR + timedelta(hours=2))

        assert_that(
            hours,
            contains_exactly(
                has_properties(hour=HOUR, calls=2, errors=1),
                has_properties(hour=HOUR + timedelta(hours=1), calls=1, errors=0),
            ),
        )


def test_tool_calls_stored_since_a_cursor_carry_only_the_argument_keys_asked_for():
    with given(_GIVEN) as context:
        agent = context.agent
        cursor = datetime.now(UTC) - timedelta(minutes=30)
        _save(
            context,
            _tool_call(agent, at=HOUR, arguments={"url": "https://old.example"}, created_at=cursor),
            _tool_call(
                agent,
                at=HOUR,
                tool_name="write_file",
                arguments={"path": "/notes.md", "content": "customer data"},
                created_at=cursor + timedelta(minutes=2),
            ),
            _tool_call(
                agent,
                at=HOUR,
                arguments={"url": "https://new.example", "maxChars": 500},
                created_at=cursor + timedelta(minutes=1),
            ),
            _tool_call(context.other_org_agent, at=HOUR, created_at=cursor + timedelta(minutes=1)),
        )

        calls = context.injector.get(ToolCallService).tool_calls_stored_between(
            agent.id, after=cursor, until=datetime.now(UTC), argument_keys=("url", "urls", "command")
        )

        assert_that(
            calls,
            contains_exactly(
                has_properties(tool_name="web_fetch", arguments={"url": "https://new.example"}),
                has_properties(tool_name="write_file", arguments={}),
            ),
        )


def test_llm_calls_and_tokens_are_counted_per_hour_without_memory_processing():
    with given(_GIVEN) as context:
        agent = context.agent
        _save(
            context,
            _cost(agent, at=HOUR + timedelta(minutes=1), tokens=100),
            _cost(agent, at=HOUR + timedelta(minutes=2), tokens=250),
            _cost(agent, at=HOUR + timedelta(minutes=3), tokens=999, is_memory=True),
            _cost(context.other_org_agent, at=HOUR + timedelta(minutes=1), tokens=5),
        )

        hours = context.injector.get(CostService).hourly_llm_usage(agent.id, HOUR, HOUR + timedelta(hours=1))

        assert_that(hours, contains_exactly(has_properties(hour=HOUR, calls=2, tokens=350)))


def test_the_last_completed_cost_sync_is_reported():
    with given(_GIVEN) as context:
        _save(context, CostSyncState(source="litellm", completed_at=HOUR))

        assert_that(context.injector.get(CostService).last_sync_completed_at(), equal_to(HOUR))


def test_writes_are_counted_per_hour():
    with given(_GIVEN) as context:
        agent = context.agent
        rows = [
            *_action(context, agent, at=HOUR + timedelta(minutes=1), integration="crm", verb="delete", is_write=True),
            *_action(context, agent, at=HOUR + timedelta(minutes=2), integration="crm", verb="update", is_write=True),
            *_action(context, agent, at=HOUR + timedelta(minutes=3), integration="crm", verb="read", is_write=False),
        ]
        _save(context, *rows)

        hours = context.injector.get(BusinessValueService).hourly_writes(agent.id, HOUR, HOUR + timedelta(hours=1))

        assert_that(hours, contains_exactly(has_properties(hour=HOUR, writes=2)))


def test_business_actions_stored_since_a_cursor_name_their_integration_and_verb():
    with given(_GIVEN) as context:
        agent = context.agent
        cursor = datetime.now(UTC) - timedelta(minutes=30)
        rows = [
            *_action(context, agent, at=HOUR, integration="crm", verb="read", is_write=False, created_at=cursor),
            *_action(
                context,
                agent,
                at=HOUR,
                integration="crm",
                verb="delete",
                is_write=True,
                created_at=cursor + timedelta(minutes=1),
            ),
        ]
        _save(context, *rows)

        actions = context.injector.get(BusinessValueService).business_actions_stored_between(
            agent.id, after=cursor, until=datetime.now(UTC)
        )

        assert_that(actions, contains_exactly(has_properties(integration="crm", verb="delete", occurred_at=HOUR)))
