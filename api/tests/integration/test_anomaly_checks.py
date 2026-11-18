"""The scheduled anomaly check (AF-453).

The contract under test:

- only Agents in Organizations that turned detection on are checked;
- each rate (tokens, LLM calls, tool calls, tool error rate, writes) is compared with
  the Agent's own active hours over the last 14 days, and a spike is recorded with
  the observed value, the usual value and when it happened;
- an ongoing deviation stays one Anomaly, and a new one starts once it has ended;
- first use of a tool, integration, integration action or destination is recorded,
  but the first check of an Agent only learns what it already uses;
- nothing is flagged before the Agent has been active on enough days, except hard caps;
- LLM figures stop where the cost sync has got to.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from hamcrest import assert_that, contains_exactly, empty, equal_to, has_length, has_properties, not_none
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.anomalies.models import (
    AgentActivitySeen,
    AgentAnomaly,
    AgentAnomalyOverride,
    AnomalySignal,
    OrganizationAnomalySettings,
    SeenKind,
)
from api.domains.anomalies.repository import Actor, AnomalySettingsRepository
from api.domains.anomalies.service import AnomalyCheckService
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.costs.models import CostRecord, CostSyncState
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.cost import cost_records_are_clean
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

# A fixed clock, so windows and cursors are exact. Rows carry their own storage time.
NOW = datetime(2026, 11, 16, 12, 30, tzinfo=UTC)
LATER = NOW + timedelta(minutes=15)
HISTORY_DAYS = (2, 3, 4, 5)
HISTORY_HOURS = (9, 10, 11)
KNOWN_HOST = "known.example.com"


def detection_is_enabled():
    def step(context):
        _save(context, OrganizationAnomalySettings(organization_id=context.organization.id, enabled=True))

    return step


def costs_are_synced_until(at: datetime):
    def step(context):
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            session.merge(CostSyncState(source="litellm", completed_at=at))
            session.commit()

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
    there_is_an_organization(),
    there_is_an_agent(),
]
_ENABLED = [*_GIVEN, detection_is_enabled(), costs_are_synced_until(NOW)]


def _save(context, *rows) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        for row in rows:
            session.add(row)
            session.flush()
        session.commit()


def _tool_call(
    agent,
    at: datetime,
    *,
    tool_name: str = "web_fetch",
    arguments: dict[str, Any] | None = None,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
) -> ToolCall:
    row = ToolCall(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        session_id="s",
        external_id=f"tc-{uuid4().hex}",
        tool_name=tool_name,
        arguments={"url": f"https://{KNOWN_HOST}/page"} if arguments is None else arguments,
        status=status,
        occurred_at=at,
    )
    row.created_at = at
    return row


def _cost(agent, at: datetime, *, tokens: int = 1_000, failed: bool = False) -> CostRecord:
    row = CostRecord(
        request_id=f"req-{uuid4().hex}",
        litellm_key_hash="hash",
        occurred_at=at,
        spend=Decimal(0) if failed else Decimal("0.01"),
        total_tokens=0 if failed else tokens,
        model="m",
        status="failure" if failed else "success",
        agent_id=agent.id,
        organization_id=agent.organization_id,
    )
    row.created_at = at
    return row


def _action(agent, at: datetime, *, integration: str = "crm", verb: str = "read", is_write: bool = False) -> list:
    tool_call = _tool_call(agent, at, tool_name="terminal", arguments={"command": f"aai-cli {integration}"})
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
    action.created_at = at
    return [tool_call, action]


def _spread(start: datetime, count: int, minutes: int = 50) -> list[datetime]:
    return [start + timedelta(seconds=index * minutes * 60 // max(count, 1)) for index in range(count)]


def usual_activity(days: tuple[int, ...] = HISTORY_DAYS, *, per_hour: int = 10):
    """`per_hour` tool calls (one of them a crm read) and LLM calls in a few hours of
    each day."""

    def step(context):
        agent = context.agent
        rows: list = []
        for day in days:
            for hour in HISTORY_HOURS:
                start = (NOW - timedelta(days=day)).replace(hour=hour, minute=0)
                times = _spread(start, per_hour)
                rows.extend(_cost(agent, at) for at in times)
                rows.extend(_tool_call(agent, at) for at in times[:-1])
                rows.extend(_action(agent, times[-1]))
        _save(context, *rows)

    return step


def _check(context, now: datetime = NOW) -> None:
    context.injector.get(AnomalyCheckService).run_checks(now)


def _anomalies(context, signal: AnomalySignal | None = None) -> list[AgentAnomaly]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        query = select(AgentAnomaly).where(col(AgentAnomaly.agent_id) == context.agent.id)
        if signal is not None:
            query = query.where(col(AgentAnomaly.signal) == signal.value)
        return list(session.exec(query.order_by(col(AgentAnomaly.started_at))).all())


def _in_last_hour(now: datetime = NOW) -> datetime:
    return now - timedelta(minutes=40)


def test_agents_in_organizations_without_detection_are_not_checked():
    with given([*_GIVEN, costs_are_synced_until(NOW), usual_activity()]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 300, minutes=30)])

        _check(context)

        assert_that(_anomalies(context), empty())


def test_a_tool_call_spike_is_recorded_with_the_usual_and_observed_values():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
            contains_exactly(has_properties(observed_value=200, usual_value=10, ended_at=None, subject=None)),
        )


def test_ordinary_activity_is_not_flagged():
    with given([*_ENABLED, usual_activity()]) as context:
        rows = []
        for at in _spread(_in_last_hour(), 10, minutes=30):
            rows += [_tool_call(context.agent, at), _cost(context.agent, at)]
        _save(context, *rows)

        _check(context)

        assert_that(_anomalies(context), empty())


def test_an_ongoing_spike_stays_one_anomaly():
    with given([*_ENABLED, usual_activity(), costs_are_synced_until(LATER)]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])
        _check(context)

        with when("the next check still sees the spike"):
            _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(LATER), 300, minutes=30)])
            _check(context, LATER)

        with then("it is the same Anomaly, brought up to date"):
            (anomaly,) = _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR)
            assert_that(anomaly, has_properties(ended_at=None, last_observed_at=LATER - timedelta(minutes=2)))


def test_a_spike_ends_once_a_check_no_longer_sees_it_and_a_later_one_starts_anew():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])
        _check(context)

        with when("a check two hours later sees ordinary activity"):
            quiet = NOW + timedelta(hours=2)
            _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(quiet), 10, minutes=30)])
            _check(context, quiet)

        with then("the Anomaly has ended"):
            (ended,) = _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR)
            assert_that(ended.ended_at, equal_to(quiet - timedelta(minutes=2)))

        with when("the Agent spikes again"):
            again = NOW + timedelta(hours=4)
            _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(again), 200, minutes=30)])
            _check(context, again)

        with then("a second Anomaly is recorded"):
            assert_that(_anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR), has_length(2))


def test_an_agent_without_enough_history_is_not_flagged_for_a_spike():
    with given([*_ENABLED, usual_activity(days=(2, 3))]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])

        _check(context)

        assert_that(_anomalies(context), empty())


def test_a_hard_cap_fires_even_without_history():
    with given(_ENABLED) as context:
        _save(
            context,
            AgentAnomalyOverride(
                organization_id=context.organization.id, agent_id=context.agent.id, max_llm_calls_per_hour=50
            ),
            *[_cost(context.agent, at) for at in _spread(_in_last_hour(), 60, minutes=30)],
        )

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.LLM_CALLS_CAP),
            contains_exactly(has_properties(observed_value=60, threshold=50, usual_value=None)),
        )


def test_a_token_spike_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *[_cost(context.agent, at, tokens=50_000) for at in _spread(_in_last_hour(), 10, minutes=30)])

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.LLM_TOKENS_PER_HOUR),
            contains_exactly(has_properties(observed_value=500_000, usual_value=10_000)),
        )


def test_llm_calls_the_cost_sync_has_not_reached_are_left_for_a_later_check():
    with given([*_ENABLED, usual_activity(), costs_are_synced_until(NOW - timedelta(minutes=50))]) as context:
        # Synced up to 50 minutes ago; the spike is after it.
        _save(
            context, *[_cost(context.agent, at, tokens=50_000) for at in _spread(NOW - timedelta(minutes=30), 10, 20)]
        )

        _check(context)

        assert_that(_anomalies(context, AnomalySignal.LLM_TOKENS_PER_HOUR), empty())


def test_a_jump_in_the_tool_error_rate_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        rows = [
            _tool_call(context.agent, at, status=ToolCallStatus.ERROR if index < 16 else ToolCallStatus.SUCCESS)
            for index, at in enumerate(_spread(_in_last_hour(), 20, minutes=30))
        ]
        _save(context, *rows)

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.TOOL_ERROR_RATE),
            contains_exactly(has_properties(observed_value=0.8, usual_value=0.0)),
        )


def _model_calls(agent, start: datetime, *, succeeded: int, failed: int, minutes: int = 30) -> list:
    times = _spread(start, succeeded + failed, minutes)
    return [_cost(agent, at, failed=index >= succeeded) for index, at in enumerate(times)]


def test_failed_model_calls_are_not_counted_as_model_calls():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *_model_calls(context.agent, _in_last_hour(), succeeded=10, failed=40))

        _check(context)

        assert_that(_anomalies(context, AnomalySignal.LLM_CALLS_PER_HOUR), empty())


def test_hours_with_only_failed_model_calls_do_not_count_as_active():
    with given([*_ENABLED, usual_activity()]) as context:
        # A scheduled job whose model calls all fail, every few hours of every day.
        rows = []
        for day in range(1, 14):
            for hour in (0, 3, 6, 15, 18, 21):
                start = (NOW - timedelta(days=day)).replace(hour=hour, minute=0)
                rows += _model_calls(context.agent, start, succeeded=0, failed=4)
        _save(context, *rows)
        service = context.injector.get(AnomalyCheckService)

        history = service.history(context.agent.id, *service.windows(NOW))

        assert_that(history.llm_calls, equal_to([10.0] * 12))
        assert_that(history.tool_calls, equal_to([10.0] * 12))
        assert_that(history.active_days, equal_to(4))


def test_a_jump_in_the_model_error_rate_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *_model_calls(context.agent, _in_last_hour(), succeeded=4, failed=16))

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.LLM_ERROR_RATE),
            contains_exactly(has_properties(observed_value=0.8, usual_value=0.0)),
        )


def test_hours_where_every_model_call_failed_are_not_learned_as_the_usual_error_rate():
    with given([*_ENABLED, usual_activity()]) as context:
        # An outage most days: if those hours were learned, failing would look normal.
        rows = []
        for day in HISTORY_DAYS:
            for hour in (13, 14, 15, 16, 17):
                start = (NOW - timedelta(days=day)).replace(hour=hour, minute=0)
                rows += _model_calls(context.agent, start, succeeded=0, failed=20)
        rows += _model_calls(context.agent, _in_last_hour(), succeeded=0, failed=20)
        _save(context, *rows)

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.LLM_ERROR_RATE),
            contains_exactly(has_properties(observed_value=1.0, usual_value=0.0)),
        )


def test_a_model_error_rate_anomaly_ends_when_the_cost_sync_has_stopped():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *_model_calls(context.agent, _in_last_hour(), succeeded=4, failed=16))
        _check(context)

        _check(context, NOW + timedelta(hours=3))

        assert_that(
            _anomalies(context, AnomalySignal.LLM_ERROR_RATE),
            contains_exactly(has_properties(ended_at=NOW)),
        )


def test_a_burst_of_writes_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        rows = []
        for at in _spread(_in_last_hour(), 25, minutes=30):
            rows += _action(context.agent, at, verb="delete", is_write=True)
        _save(context, *rows)

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.WRITES_PER_HOUR), contains_exactly(has_properties(observed_value=25))
        )


def test_the_first_check_learns_what_the_agent_already_uses_without_flagging_it():
    with given([*_ENABLED, usual_activity()]) as context:
        _check(context)

        assert_that(_anomalies(context), empty())


def _learned_then(context, rows: list) -> None:
    """A first check learns the Agent's history; `rows` arrive before the next one."""
    _check(context)
    _save(context, *rows)
    _check(context, LATER)


def test_first_use_of_a_destination_is_recorded_by_host():
    with given([*_ENABLED, usual_activity()]) as context:
        at = NOW + timedelta(minutes=1)
        _learned_then(
            context,
            [
                _tool_call(context.agent, at, arguments={"url": "https://new.example.org/path?q=secret"}),
                _tool_call(context.agent, at, arguments={"url": f"https://{KNOWN_HOST}/other"}),
            ],
        )

        assert_that(
            _anomalies(context, AnomalySignal.NEW_DESTINATION),
            contains_exactly(has_properties(subject="new.example.org", started_at=at, ended_at=at)),
        )


def test_first_use_of_a_destination_in_a_shell_command_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        at = NOW + timedelta(minutes=1)
        _learned_then(
            context,
            [
                _tool_call(
                    context.agent, at, tool_name="terminal", arguments={"command": "curl -s https://api.new.io/x"}
                )
            ],
        )

        assert_that(
            _anomalies(context, AnomalySignal.NEW_DESTINATION), contains_exactly(has_properties(subject="api.new.io"))
        )


def test_first_use_of_a_tool_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        at = NOW + timedelta(minutes=1)
        _learned_then(context, [_tool_call(context.agent, at, tool_name="browser_exec", arguments={"code": "x"})])

        assert_that(
            _anomalies(context, AnomalySignal.NEW_TOOL), contains_exactly(has_properties(subject="browser_exec"))
        )


def test_first_use_of_an_action_on_a_known_integration_is_recorded():
    with given([*_ENABLED, usual_activity()]) as context:
        _learned_then(context, _action(context.agent, NOW + timedelta(minutes=1), verb="delete", is_write=True))

        assert_that(
            _anomalies(context, AnomalySignal.NEW_INTEGRATION_ACTION),
            contains_exactly(has_properties(subject="crm delete")),
        )
        assert_that(_anomalies(context, AnomalySignal.NEW_INTEGRATION), empty())


def test_first_use_of_an_integration_is_recorded_once_not_also_as_an_action():
    with given([*_ENABLED, usual_activity()]) as context:
        _learned_then(context, _action(context.agent, NOW + timedelta(minutes=1), integration="erp", verb="export"))

        assert_that(
            [(anomaly.signal, anomaly.subject) for anomaly in _anomalies(context)],
            equal_to([(AnomalySignal.NEW_INTEGRATION.value, "erp")]),
        )


def test_something_last_used_before_the_baseline_window_counts_as_new_again():
    with given([*_ENABLED, usual_activity()]) as context:
        old = NOW - timedelta(days=20)
        _save(
            context,
            AgentActivitySeen(
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                kind=SeenKind.DESTINATION.value,
                subject="returning.example.com",
                first_seen_at=old,
                last_seen_at=old,
            ),
        )
        at = NOW + timedelta(minutes=1)
        _learned_then(context, [_tool_call(context.agent, at, arguments={"url": "https://returning.example.com"})])

        assert_that(
            _anomalies(context, AnomalySignal.NEW_DESTINATION),
            contains_exactly(has_properties(subject="returning.example.com")),
        )


def test_first_use_is_not_flagged_before_the_agent_has_enough_history():
    with given([*_ENABLED, usual_activity(days=(2,))]) as context:
        at = NOW + timedelta(minutes=1)
        _learned_then(context, [_tool_call(context.agent, at, arguments={"url": "https://new.example.org"})])

        assert_that(_anomalies(context), empty())


def test_turning_detection_off_and_on_again_relearns_instead_of_flagging_the_gap():
    with given([*_ENABLED, usual_activity()]) as context:
        _check(context)

        with when("detection is off while the Agent starts using a new host, then on again"):
            _set_enabled(context, False)
            _save(
                context, _tool_call(context.agent, NOW + timedelta(minutes=1), arguments={"url": "https://gap.example"})
            )
            _set_enabled(context, True)
            _check(context, LATER)

        with then("what happened while it was off is learned, not flagged"):
            assert_that(_anomalies(context, AnomalySignal.NEW_DESTINATION), empty())


def _set_enabled(context, enabled: bool) -> None:
    actor = Actor(identity=ActorIdentity(type=ActorIdentityType.SYSTEM, id=uuid4()), display="test")
    context.injector.get(AnomalySettingsRepository).set_enabled_with_event(
        context.organization.id, enabled, actor=actor, subject_display="org"
    )


def test_turning_detection_off_ends_what_was_ongoing():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])
        _check(context)

        with when("detection is turned off, and later back on while the spike goes on"):
            _set_enabled(context, False)
            ended_by_turning_off = _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR)[0].ended_at
            _set_enabled(context, True)
            _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(LATER), 300, minutes=30)])
            _check(context, LATER)

        with then("the first Anomaly ended when detection was turned off, and a new one started"):
            assert_that(ended_by_turning_off, not_none())
            assert_that(
                _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
                contains_exactly(
                    has_properties(started_at=NOW - timedelta(minutes=2), ended_at=not_none()),
                    has_properties(started_at=LATER - timedelta(minutes=2), ended_at=None),
                ),
            )


def test_an_ongoing_anomaly_ends_once_its_agent_is_deleted():
    with given([*_ENABLED, usual_activity(), costs_are_synced_until(LATER)]) as context:
        _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])
        _check(context)

        with when("the Agent is deleted before the next check"):
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                agent = session.get(Agent, context.agent.id)
                assert agent is not None
                agent.deleted_at = NOW + timedelta(minutes=5)
                session.add(agent)
                session.commit()
            _check(context, LATER)

        with then("its Anomaly has ended"):
            assert_that(
                _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
                contains_exactly(has_properties(ended_at=LATER - timedelta(minutes=2))),
            )


def _stored_late(row, stored_at: datetime):
    row.created_at = stored_at
    return row


def _ledger_subjects(context, kind: SeenKind) -> list[str]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        query = select(col(AgentActivitySeen.subject)).where(
            col(AgentActivitySeen.agent_id) == context.agent.id, col(AgentActivitySeen.kind) == kind.value
        )
        return sorted(session.exec(query).all())


def test_activity_from_before_the_baseline_window_is_not_read_even_when_stored_since():
    with given([*_ENABLED, usual_activity()]) as context:
        stored = NOW + timedelta(minutes=1)
        _learned_then(
            context,
            [
                _stored_late(
                    _tool_call(context.agent, NOW - timedelta(days=20), arguments={"url": "https://ancient.example"}),
                    stored,
                )
            ],
        )

        assert_that(_ledger_subjects(context, SeenKind.DESTINATION), equal_to([KNOWN_HOST]))


def test_activity_stored_long_after_it_happened_is_learned_not_flagged():
    # A backfill stores rows today for what the Agent did days ago.
    with given([*_ENABLED, usual_activity()]) as context:
        stored = NOW + timedelta(minutes=1)
        _learned_then(
            context,
            [
                _stored_late(
                    _tool_call(context.agent, NOW - timedelta(days=5), arguments={"url": "https://backfilled.example"}),
                    stored,
                ),
                *[
                    _stored_late(row, stored)
                    for row in _action(context.agent, NOW - timedelta(days=5), integration="erp", verb="export")
                ],
            ],
        )

        assert_that(_anomalies(context), empty())
        assert_that(_ledger_subjects(context, SeenKind.DESTINATION), equal_to(["backfilled.example", KNOWN_HOST]))
        assert_that(_ledger_subjects(context, SeenKind.INTEGRATION), equal_to(["crm", "erp"]))


def test_a_use_backfilled_alongside_a_recent_one_is_not_new():
    with given([*_ENABLED, usual_activity()]) as context:
        stored = NOW + timedelta(minutes=1)
        _learned_then(
            context,
            [
                _stored_late(
                    _tool_call(context.agent, NOW - timedelta(days=5), arguments={"url": "https://both.example"}),
                    stored,
                ),
                _tool_call(context.agent, stored, arguments={"url": "https://both.example"}),
            ],
        )

        assert_that(_anomalies(context, AnomalySignal.NEW_DESTINATION), empty())


def test_a_new_use_stored_a_little_late_is_still_flagged():
    with given([*_ENABLED, usual_activity()]) as context:
        # Happened just before the previous check read through, stored just after.
        happened = NOW - timedelta(minutes=10)
        _learned_then(
            context,
            [
                _stored_late(
                    _tool_call(context.agent, happened, arguments={"url": "https://late.example"}),
                    NOW + timedelta(minutes=1),
                )
            ],
        )

        assert_that(
            _anomalies(context, AnomalySignal.NEW_DESTINATION),
            contains_exactly(has_properties(subject="late.example", started_at=happened)),
        )


def test_hours_the_cost_sync_has_not_reached_do_not_count_as_hours_without_llm_calls():
    synced = NOW - timedelta(minutes=50)
    with given([*_ENABLED, usual_activity(), costs_are_synced_until(synced)]) as context:
        # Tool calls in an hour whose LLM calls are not all synced yet.
        today_ten = NOW.replace(hour=10, minute=0)
        _save(context, *[_tool_call(context.agent, at) for at in _spread(today_ten, 10)])
        service = context.injector.get(AnomalyCheckService)

        history = service.history(context.agent.id, *service.windows(NOW))

        assert_that(history.llm_calls, equal_to([10.0] * 12))
        assert_that(history.tool_calls, has_length(13))


def test_the_oldest_hour_of_the_baseline_window_counts_whole():
    with given(_ENABLED) as context:
        until = NOW - timedelta(minutes=2)
        oldest_hour = (until - timedelta(days=14)).replace(minute=0)
        _save(context, *[_tool_call(context.agent, oldest_hour + timedelta(minutes=minute)) for minute in (5, 40)])
        service = context.injector.get(AnomalyCheckService)

        history = service.history(context.agent.id, *service.windows(NOW))

        assert_that(history.tool_calls, equal_to([2.0]))


def test_llm_anomalies_end_when_the_cost_sync_has_stopped():
    with given([*_ENABLED, usual_activity()]) as context:
        _save(context, *[_cost(context.agent, at, tokens=50_000) for at in _spread(_in_last_hour(), 10, minutes=30)])
        _check(context)

        with when("checks go on for hours with no cost sync since"):
            _check(context, NOW + timedelta(hours=3))

        with then("the Anomaly ends where the synced figures stop, rather than staying open"):
            assert_that(
                _anomalies(context, AnomalySignal.LLM_TOKENS_PER_HOUR),
                contains_exactly(has_properties(ended_at=NOW)),
            )
