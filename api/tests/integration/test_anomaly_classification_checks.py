"""The scheduled check classifies what it flags with the decision model (AF-459).

The contract under test:

- everything newly flagged for an Agent in one check is classified in one decision,
  billed to that Agent, and the Anomaly keeps the category, severity and full answer;
- what was flagged earlier and is still ongoing is given as context, not asked again;
- if the decision fails for any reason, including the Agent's spend limit, the Anomaly
  stays as the statistics flagged it, is not retried, and the check carries on;
- a destination's host never reaches the provider;
- Hermes and OpenClaw Agents are classified alike.
"""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from hamcrest import assert_that, contains_exactly, contains_inanyorder, equal_to, has_entries, has_properties

from api.domains.agents.models import AgentType
from api.domains.anomalies.models import AnomalySignal, ClassificationState
from api.domains.anomalies.service import AnomalyCheckService
from api.domains.decisions.service import DecisionService
from api.infrastructure.litellm.decisions import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionFailure,
    DecisionResult,
    ScoreAnswer,
    ScoreQuestion,
    YesNoAnswer,
    YesNoQuestion,
)
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.integration.test_anomaly_checks import (
    LATER,
    NOW,
    _anomalies,
    _check,
    _in_last_hour,
    _learned_then,
    _save,
    _spread,
    _tool_call,
    costs_are_synced_until,
    detection_is_enabled,
    usual_activity,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.cost import cost_records_are_clean
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

NEW_HOST = "portal.customer-of-ours.example"


def _given(*steps, agent_type: AgentType = AgentType.OPENCLAW):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        cost_records_are_clean(),
        there_is_an_organization(),
        there_is_an_agent(agent_type=agent_type),
        detection_is_enabled(),
        costs_are_synced_until(NOW),
        usual_activity(),
        *steps,
    ]


def _answers(questions, *, unusual: float, category: str, score: float):
    answers = {}
    for name, question in questions.items():
        match question:
            case YesNoQuestion():
                answers[name] = YesNoAnswer(probability=unusual)
            case ChoiceQuestion():
                answers[name] = ChoiceAnswer(choice=category, confidence=0.8, probabilities={category: 0.8})
            case ScoreQuestion():
                level = question.levels[round(score)]
                answers[name] = ScoreAnswer(score=score, level=level, confidence=0.7, probabilities={level: 0.7})
    return answers


def the_decision_model_classifies(*, unusual: float = 0.9, category: str = "RUNAWAY_LOOP", score: float = 2.0):
    def step(context):
        def decide(agent_id, state, questions):
            return DecisionResult(
                answers=_answers(questions, unusual=unusual, category=category, score=score),
                input_tokens=10,
                output_tokens=3,
            )

        context.decide = Mock(side_effect=decide)
        context.injector.get(DecisionService).decide = context.decide

    return step


def the_decision_model_fails(failure: DecisionFailure = DecisionFailure.UNAVAILABLE):
    def step(context):
        context.decide = Mock(side_effect=DecisionError(failure))
        context.injector.get(DecisionService).decide = context.decide

    return step


def _a_tool_call_spike(context) -> None:
    _save(context, *[_tool_call(context.agent, at) for at in _spread(_in_last_hour(), 200, minutes=30)])


def _sent_state(context, call: int = 0) -> dict:
    return context.decide.call_args_list[call].args[1]


def test_a_newly_flagged_spike_is_classified_and_billed_to_its_agent():
    with given(_given(the_decision_model_classifies(unusual=0.9, category="RUNAWAY_LOOP", score=2.0))) as context:
        _a_tool_call_spike(context)

        _check(context)

        assert_that(
            _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
            contains_exactly(
                has_properties(
                    classification_state=ClassificationState.CLASSIFIED.value,
                    classification_category="RUNAWAY_LOOP",
                    classification_severity=2.0,
                    classification=has_entries(unusual_probability=0.9, severity_level="HIGH"),
                )
            ),
        )
        assert_that(context.decide.call_args.args[0], equal_to(context.agent.id))


def test_everything_flagged_in_one_check_is_classified_in_one_decision():
    with given(_given(the_decision_model_classifies())) as context:
        # A spike of a tool the Agent has never used: a rate and a first use at once.
        times = _spread(NOW + timedelta(minutes=1), 200, minutes=10)
        _learned_then(context, [_tool_call(context.agent, at, tool_name="browser_exec", arguments={}) for at in times])

        assert_that(context.decide.call_count, equal_to(1))
        assert_that(
            [anomaly.signal for anomaly in _anomalies(context)],
            contains_inanyorder(AnomalySignal.TOOL_CALLS_PER_HOUR.value, AnomalySignal.NEW_TOOL.value),
        )
        assert_that(
            [anomaly.classification_state for anomaly in _anomalies(context)],
            equal_to([ClassificationState.CLASSIFIED.value] * 2),
        )


def test_an_ongoing_anomaly_is_not_classified_again():
    with given(_given(the_decision_model_classifies())) as context:
        _a_tool_call_spike(context)

        _check(context)
        _check(context, LATER)

        assert_that(_anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR), contains_exactly(has_properties(ended_at=None)))
        assert_that(context.decide.call_count, equal_to(1))


def test_what_is_still_ongoing_is_given_as_context_for_what_is_new():
    with given(_given(the_decision_model_classifies())) as context:
        _a_tool_call_spike(context)
        _check(context)
        _save(context, _tool_call(context.agent, NOW + timedelta(minutes=1), tool_name="browser_exec", arguments={}))

        _check(context, LATER)

        assert_that(
            _sent_state(context, call=1),
            has_entries(
                flagged=contains_exactly(has_entries(signal="NEW_TOOL", subject="browser_exec")),
                also_ongoing=["TOOL_CALLS_PER_HOUR"],
            ),
        )


@pytest.mark.parametrize(
    "failure",
    [DecisionFailure.BUDGET_EXCEEDED, DecisionFailure.UNAVAILABLE, DecisionFailure.KEY_OR_MODEL_REJECTED, DecisionFailure.BAD_RESPONSE],
)
def test_a_failed_classification_leaves_the_anomaly_as_flagged_by_statistics(failure):
    with given(_given(the_decision_model_fails(failure))) as context:
        _a_tool_call_spike(context)

        summary = context.injector.get(AnomalyCheckService).run_checks(NOW)

        assert_that(summary.failures, equal_to(0))
        assert_that(
            _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
            contains_exactly(
                has_properties(
                    observed_value=200,
                    classification_state=ClassificationState.STATISTICS_ONLY.value,
                    classification_category=None,
                    classification_severity=None,
                    classification=None,
                )
            ),
        )


def test_a_failed_classification_is_not_retried():
    with given(_given(the_decision_model_fails(DecisionFailure.BUDGET_EXCEEDED))) as context:
        _a_tool_call_spike(context)
        _check(context)
        the_decision_model_classifies()(context)

        _check(context, LATER)

        assert_that(context.decide.call_count, equal_to(0))
        assert_that(
            _anomalies(context, AnomalySignal.TOOL_CALLS_PER_HOUR),
            contains_exactly(has_properties(classification_state=ClassificationState.STATISTICS_ONLY.value)),
        )


@pytest.mark.parametrize(
    "agent_type, tool_name, arguments",
    [
        (AgentType.OPENCLAW, "web_fetch", {"url": f"https://{NEW_HOST}/account?id=42"}),
        (AgentType.HERMES, "browser_navigate", {"url": f"https://{NEW_HOST}/account?id=42"}),
        (AgentType.OPENCLAW, "exec", {"command": f"curl -s https://{NEW_HOST}/export"}),
        (AgentType.HERMES, "terminal", {"command": f"curl -s https://{NEW_HOST}/export"}),
    ],
)
def test_a_new_destination_is_classified_on_both_runtimes_without_its_host(agent_type, tool_name, arguments):
    with given(_given(the_decision_model_classifies(category="RISKY_ACTION"), agent_type=agent_type)) as context:
        _learned_then(context, [_tool_call(context.agent, NOW + timedelta(minutes=1), tool_name=tool_name, arguments=arguments)])

        assert_that(
            _anomalies(context, AnomalySignal.NEW_DESTINATION),
            contains_exactly(
                has_properties(
                    subject=NEW_HOST,
                    classification_state=ClassificationState.CLASSIFIED.value,
                    classification_category="RISKY_ACTION",
                )
            ),
        )
        sent = str(context.decide.call_args_list)
        assert NEW_HOST not in sent
        assert "account?id=42" not in sent
