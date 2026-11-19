"""What the decision model is told about flagged activity, and how its answers are read (AF-459).

Only derived features go to the provider: what was flagged, how far from usual, for
how long, and next to what else. Never identifiers, timestamps or raw arguments, and
never a destination's host.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hamcrest import (
    assert_that,
    close_to,
    contains_exactly,
    equal_to,
    has_entries,
    has_key,
    has_length,
    has_properties,
    instance_of,
    is_,
    is_not,
    none,
)

from api.domains.anomalies.classification import (
    CATEGORIES,
    MAX_ITEMS_PER_DECISION,
    SEVERITY_LEVELS,
    AgentContext,
    classification_request,
    read_classifications,
)
from api.domains.anomalies.detection import Sensitivity
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal
from api.infrastructure.litellm.decisions import (
    MAX_QUESTIONS,
    ChoiceAnswer,
    ChoiceQuestion,
    ScoreAnswer,
    ScoreQuestion,
    YesNoAnswer,
    YesNoQuestion,
)

STARTED = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)
CONTEXT = AgentContext(sensitivity=Sensitivity.HIGH, active_days=9)


def _rate(signal=AnomalySignal.TOOL_CALLS_PER_HOUR, *, observed=400.0, usual=100.0, threshold=150.0, ended=None):
    return AgentAnomaly(
        organization_id=uuid4(),
        agent_id=uuid4(),
        signal=signal.value,
        observed_value=observed,
        usual_value=usual,
        threshold=threshold,
        started_at=STARTED,
        last_observed_at=STARTED + timedelta(minutes=45),
        ended_at=ended,
    )


def _first_use(signal: AnomalySignal, subject: str, uses: int = 3):
    return AgentAnomaly(
        organization_id=uuid4(),
        agent_id=uuid4(),
        signal=signal.value,
        subject=subject,
        observed_value=uses,
        started_at=STARTED,
        last_observed_at=STARTED,
        ended_at=STARTED,
    )


def _cap(observed=900.0, cap=500.0):
    return AgentAnomaly(
        organization_id=uuid4(),
        agent_id=uuid4(),
        signal=AnomalySignal.LLM_CALLS_CAP.value,
        observed_value=observed,
        threshold=cap,
        started_at=STARTED,
        last_observed_at=STARTED,
    )


def test_a_rate_is_described_by_how_far_it_went_from_usual_and_for_how_long():
    state, _ = classification_request([_rate()], CONTEXT, other_ongoing=[])

    assert_that(
        state["flagged"],
        contains_exactly(
            has_entries(
                ref="a1",
                signal="TOOL_CALLS_PER_HOUR",
                kind="rate",
                observed=400.0,
                usual=100.0,
                threshold=150.0,
                times_usual=4.0,
                times_threshold=close_to(2.667, 1e-3),
                ongoing=True,
                minutes_flagged=45,
            )
        ),
    )


def test_the_agent_is_described_by_its_sensitivity_and_history():
    state, _ = classification_request([_rate()], CONTEXT, other_ongoing=[])

    assert_that(state["agent"], equal_to({"sensitivity": "HIGH", "active_days_in_last_14": 9}))


def test_a_usual_value_of_zero_gives_no_multiple_of_usual():
    state, _ = classification_request([_rate(usual=0.0)], CONTEXT, other_ongoing=[])

    assert_that(state["flagged"][0]["times_usual"], is_(none()))


def test_an_ended_rate_is_not_ongoing():
    state, _ = classification_request([_rate(ended=STARTED + timedelta(hours=1))], CONTEXT, other_ongoing=[])

    assert_that(state["flagged"][0], has_entries(ongoing=False, minutes_flagged=45))


def test_a_cap_is_described_against_the_cap_with_no_usual_value():
    state, _ = classification_request([_cap()], CONTEXT, other_ongoing=[])

    assert_that(
        state["flagged"][0],
        has_entries(kind="cap", observed=900.0, usual=None, threshold=500.0, times_usual=None, times_threshold=1.8),
    )


@pytest.mark.parametrize(
    "signal, subject",
    [
        (AnomalySignal.NEW_TOOL, "web_fetch"),
        (AnomalySignal.NEW_INTEGRATION, "crm"),
        (AnomalySignal.NEW_INTEGRATION_ACTION, "crm delete"),
    ],
)
def test_a_first_use_of_a_tool_or_integration_names_it(signal, subject):
    state, _ = classification_request([_first_use(signal, subject, uses=3)], CONTEXT, other_ongoing=[])

    assert_that(state["flagged"][0], equal_to({"ref": "a1", "signal": signal.value, "kind": "first_use", "subject": subject, "uses": 3}))


def test_a_new_destination_never_sends_its_host():
    host = "customer-portal.example.com"

    state, _ = classification_request(
        [_first_use(AnomalySignal.NEW_DESTINATION, host)], CONTEXT, other_ongoing=[]
    )

    assert_that(state["flagged"][0], is_not(has_key("subject")))
    assert host not in json.dumps(state)


def test_no_identifiers_or_timestamps_reach_the_provider():
    anomaly = _rate()

    state, _ = classification_request([anomaly], CONTEXT, other_ongoing=[])

    sent = json.dumps(state)
    for value in (anomaly.id, anomaly.agent_id, anomaly.organization_id):
        assert str(value) not in sent
    assert STARTED.isoformat() not in sent
    assert "2026" not in sent


def test_other_ongoing_activity_is_given_as_context():
    state, _ = classification_request(
        [_rate()],
        CONTEXT,
        other_ongoing=[AnomalySignal.LLM_TOKENS_PER_HOUR, AnomalySignal.TOOL_ERROR_RATE],
    )

    assert_that(state["also_ongoing"], equal_to(["LLM_TOKENS_PER_HOUR", "TOOL_ERROR_RATE"]))


def test_each_flagged_item_gets_an_unusual_a_category_and_a_severity_question():
    _, questions = classification_request([_rate(), _cap()], CONTEXT, other_ongoing=[])

    assert_that(list(questions), equal_to(["a1_unusual", "a1_category", "a1_severity", "a2_unusual", "a2_category", "a2_severity"]))
    assert_that(questions["a1_unusual"], instance_of(YesNoQuestion))
    assert_that(questions["a1_category"], has_properties(options=CATEGORIES))
    assert_that(questions["a1_category"], instance_of(ChoiceQuestion))
    assert_that(questions["a1_severity"], instance_of(ScoreQuestion))
    assert_that(list(questions["a1_severity"].levels), equal_to(list(SEVERITY_LEVELS)))
    assert "a1" in questions["a1_unusual"].question


def test_one_decision_stays_within_the_question_limit():
    assert MAX_ITEMS_PER_DECISION * 3 <= MAX_QUESTIONS

    _, questions = classification_request([_rate()] * MAX_ITEMS_PER_DECISION, CONTEXT, other_ongoing=[])

    assert_that(questions, has_length(MAX_ITEMS_PER_DECISION * 3))


def test_more_items_than_one_decision_takes_are_refused():
    with pytest.raises(ValueError):
        classification_request([_rate()] * (MAX_ITEMS_PER_DECISION + 1), CONTEXT, other_ongoing=[])


def _answers(ref: str, *, unusual=0.85, category="RUNAWAY_LOOP", score=2.2):
    return {
        f"{ref}_unusual": YesNoAnswer(probability=unusual),
        f"{ref}_category": ChoiceAnswer(choice=category, confidence=0.7, probabilities={category: 0.7, "OTHER": 0.3}),
        f"{ref}_severity": ScoreAnswer(
            score=score, level="HIGH", confidence=0.6, probabilities={"MEDIUM": 0.3, "HIGH": 0.6, "CRITICAL": 0.1}
        ),
    }


def test_answers_are_read_back_per_flagged_item():
    first, second = _rate(), _cap()

    classifications = read_classifications(
        [first, second], {**_answers("a1"), **_answers("a2", unusual=0.1, category="MORE_WORK", score=0.3)}
    )

    assert_that(
        classifications[first.id],
        has_properties(unusual_probability=0.85, category="RUNAWAY_LOOP", severity=2.2),
    )
    assert_that(classifications[second.id], has_properties(unusual_probability=0.1, category="MORE_WORK", severity=0.3))


def test_the_full_answer_is_kept_for_the_record():
    anomaly = _rate()

    classification = read_classifications([anomaly], _answers("a1"))[anomaly.id]

    assert_that(
        classification.details,
        equal_to(
            {
                "unusual_probability": 0.85,
                "category": "RUNAWAY_LOOP",
                "category_confidence": 0.7,
                "category_probabilities": {"RUNAWAY_LOOP": 0.7, "OTHER": 0.3},
                "severity_level": "HIGH",
                "severity_score": 2.2,
                "severity_confidence": 0.6,
                "severity_probabilities": {"MEDIUM": 0.3, "HIGH": 0.6, "CRITICAL": 0.1},
            }
        ),
    )


def test_answers_of_the_wrong_type_are_refused():
    anomaly = _rate()
    answers = {**_answers("a1"), "a1_unusual": ChoiceAnswer(choice="OTHER", confidence=1.0, probabilities={})}

    with pytest.raises(ValueError):
        read_classifications([anomaly], answers)
