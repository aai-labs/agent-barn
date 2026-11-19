"""The local seed for trying anomaly detection by hand (AF-453).

It gives a real Agent a few days of steady activity, so checks flag things straight
away instead of after three active days, and optionally an unusual hour on top.
"""

from datetime import UTC, datetime

from hamcrest import assert_that, empty, equal_to, has_item, has_properties
from sqlmodel import Session, col, select

from api.domains.anomalies.models import AgentAnomaly, AgentAnomalyState, AnomalySignal, OrganizationAnomalySettings
from api.domains.anomalies.service import AnomalyCheckService
from api.domains.costs.models import CostSyncState
from api.domains.tool_calls.models import ToolCall
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.scripts.seed_anomaly_history import clear_seeded, seed, seed_history
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.cost import cost_records_are_clean
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

NOW = datetime(2026, 11, 16, 12, 30, tzinfo=UTC)


def detection_is_on_and_costs_synced():
    def step(context):
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            session.add(OrganizationAnomalySettings(organization_id=context.organization.id, enabled=True))
            session.merge(CostSyncState(source="litellm", completed_at=NOW))
            session.commit()

    return step


def there_is_another_agent_in_the_organization():
    def step(context):
        seeded = context.agent
        there_is_an_agent(name="Not Seeded")(context)
        context.other_agent, context.agent = context.agent, seeded

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
    there_is_an_organization(),
    there_is_an_agent(),
    detection_is_on_and_costs_synced(),
]


def _seed(context, *, spike: bool) -> None:
    seed(
        context.injector.get(PostgresRepositoryDelegate),
        context.injector.get(AnomalyCheckService),
        context.agent.id,
        NOW,
        spike=spike,
    )


def _anomalies(context) -> list[AgentAnomaly]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentAnomaly).where(col(AgentAnomaly.agent_id) == context.agent.id)).all())


def test_seeded_history_is_ordinary_and_enough_to_judge_by():
    with given(_GIVEN) as context:
        _seed(context, spike=False)

        assert_that(_anomalies(context), empty())


def test_a_seeded_spike_is_flagged_on_every_rate_and_as_first_uses():
    with given(_GIVEN) as context:
        _seed(context, spike=True)

        assert_that(
            {(anomaly.signal, anomaly.subject) for anomaly in _anomalies(context)},
            equal_to(
                {
                    (AnomalySignal.TOOL_CALLS_PER_HOUR.value, None),
                    (AnomalySignal.TOOL_ERROR_RATE.value, None),
                    (AnomalySignal.WRITES_PER_HOUR.value, None),
                    (AnomalySignal.LLM_CALLS_PER_HOUR.value, None),
                    (AnomalySignal.LLM_TOKENS_PER_HOUR.value, None),
                    (AnomalySignal.LLM_ERROR_RATE.value, None),
                    (AnomalySignal.NEW_DESTINATION.value, "unusual.seed.example"),
                    (AnomalySignal.NEW_INTEGRATION_ACTION.value, "crm delete"),
                }
            ),
        )


def test_clearing_removes_what_was_seeded_and_what_it_caused():
    with given(_GIVEN) as context:
        _seed(context, spike=True)

        with when("the seed is cleared"):
            clear_seeded(context.injector.get(PostgresRepositoryDelegate), context.agent.id)

        with then("the Agent has no seeded activity or Anomalies left"):
            assert_that(_anomalies(context), empty())
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                calls = session.exec(select(ToolCall).where(col(ToolCall.agent_id) == context.agent.id)).all()
            assert_that(calls, empty())


def test_the_history_counts_as_enough_days():
    with given(_GIVEN) as context:
        seed_history(context.injector.get(PostgresRepositoryDelegate), context.agent.id, NOW)
        checks = context.injector.get(AnomalyCheckService)

        history = checks.history(context.agent.id, *checks.windows(NOW))

        assert_that(history, has_properties(active_days=5))
        assert_that(history.tool_calls, has_item(11.0))


def test_seeding_again_replaces_the_earlier_seed_instead_of_adding_to_it():
    with given(_GIVEN) as context:
        _seed(context, spike=True)

        _seed(context, spike=True)

        checks = context.injector.get(AnomalyCheckService)
        history = checks.history(context.agent.id, *checks.windows(NOW))
        assert_that(history.tool_calls, equal_to([11.0] * 15))


def test_seeding_checks_only_the_seeded_agent():
    with given([*_GIVEN, there_is_another_agent_in_the_organization()]) as context:
        _seed(context, spike=True)

        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            other_state = session.exec(
                select(AgentAnomalyState).where(col(AgentAnomalyState.agent_id) == context.other_agent.id)
            ).all()
        assert_that(other_state, empty())
