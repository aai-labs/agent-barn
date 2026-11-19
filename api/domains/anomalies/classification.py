"""What a decision model is asked about flagged activity, and how its answers are read.

Pure functions: the check service collects the Anomalies and asks the model; this module
only builds the request and reads the answers.

Only derived features go to the model provider: the signal, how far the value went from
the Agent's usual and its threshold, how long it has lasted, and what else is flagged
alongside it. Never identifiers, timestamps, tool arguments or other raw records. A
first use names the tool or integration, which are the platform's own vocabulary, but
never a destination's host: a host can identify a customer.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from api.domains.anomalies.detection import Sensitivity
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal
from api.infrastructure.litellm.decisions import (
    MAX_QUESTIONS,
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    YesNoAnswer,
    YesNoQuestion,
)

CATEGORIES: dict[str, str | None] = {
    "RUNAWAY_LOOP": "The Agent repeats the same work far beyond what the job needs, burning calls or tokens.",
    "FAILING_DEPENDENCY": "A tool, integration or model the Agent relies on keeps failing.",
    "MORE_WORK": "The Agent is legitimately doing more of its usual work than usual.",
    "NEW_CAPABILITY": "The Agent starts using something new in a way that fits ordinary work.",
    "RISKY_ACTION": "The activity could cause harm or expose data, such as unusual writes, deletes or new destinations.",
    "OTHER": "None of the above.",
}
SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
QUESTIONS_PER_ITEM = 3
MAX_ITEMS_PER_DECISION = MAX_QUESTIONS // QUESTIONS_PER_ITEM

RATE_SIGNALS = frozenset(
    {
        AnomalySignal.LLM_TOKENS_PER_HOUR,
        AnomalySignal.LLM_CALLS_PER_HOUR,
        AnomalySignal.LLM_ERROR_RATE,
        AnomalySignal.TOOL_CALLS_PER_HOUR,
        AnomalySignal.TOOL_ERROR_RATE,
        AnomalySignal.WRITES_PER_HOUR,
    }
)
CAP_SIGNALS = frozenset({AnomalySignal.LLM_TOKENS_CAP, AnomalySignal.LLM_CALLS_CAP})
# First uses whose subject may be named to the provider. NEW_DESTINATION is not one.
NAMED_FIRST_USES = frozenset(
    {AnomalySignal.NEW_TOOL, AnomalySignal.NEW_INTEGRATION, AnomalySignal.NEW_INTEGRATION_ACTION}
)


@dataclass(frozen=True)
class AgentContext:
    sensitivity: Sensitivity
    active_days: int


@dataclass(frozen=True)
class Classification:
    # Probability that the activity is really unusual for the Agent, not noise.
    unusual_probability: float
    category: str
    # Probability-weighted index into SEVERITY_LEVELS, 0 for LOW.
    severity: float
    # The model's full answer, kept with the Anomaly.
    details: dict[str, Any]


def classification_request(
    anomalies: Sequence[AgentAnomaly], context: AgentContext, *, other_ongoing: Iterable[AnomalySignal]
) -> tuple[dict[str, Any], dict[str, Question]]:
    """The state and questions for one decision about `anomalies`.

    Raises ValueError for more Anomalies than one decision can take.
    """
    if not 1 <= len(anomalies) <= MAX_ITEMS_PER_DECISION:
        raise ValueError(f"Classify between 1 and {MAX_ITEMS_PER_DECISION} Anomalies at a time")
    state = {
        "agent": {"sensitivity": context.sensitivity.value, "active_days_in_last_14": context.active_days},
        "flagged": [_features(_ref(index), anomaly) for index, anomaly in enumerate(anomalies)],
        "also_ongoing": [signal.value for signal in other_ongoing],
    }
    questions: dict[str, Question] = {}
    for index in range(len(anomalies)):
        ref = _ref(index)
        questions[f"{ref}_unusual"] = YesNoQuestion(
            question=f"Is flagged item {ref} really unusual for this Agent, rather than noise in its normal work?",
            yes_means="Something has changed in what the Agent does that an Owner should look at.",
            no_means="Ordinary variation, or a change that explains itself.",
        )
        questions[f"{ref}_category"] = ChoiceQuestion(
            question=f"What kind of activity is flagged item {ref}?", options=CATEGORIES
        )
        questions[f"{ref}_severity"] = ScoreQuestion(
            question=f"How severe is flagged item {ref} for the Organization running the Agent?",
            levels=SEVERITY_LEVELS,
        )
    return state, questions


def read_classifications(anomalies: Sequence[AgentAnomaly], answers: Mapping[str, Answer]) -> dict[UUID, Classification]:
    """Each Anomaly's classification from the answers to `classification_request`'s
    questions. Raises ValueError for answers of the wrong type."""
    return {anomaly.id: _classification(_ref(index), answers) for index, anomaly in enumerate(anomalies)}


def _ref(index: int) -> str:
    return f"a{index + 1}"


def _features(ref: str, anomaly: AgentAnomaly) -> dict[str, Any]:
    signal = AnomalySignal(anomaly.signal)
    if signal not in RATE_SIGNALS and signal not in CAP_SIGNALS:
        features: dict[str, Any] = {"ref": ref, "signal": signal.value, "kind": "first_use"}
        if signal in NAMED_FIRST_USES and anomaly.subject is not None:
            features["subject"] = anomaly.subject
        features["uses"] = int(anomaly.observed_value)
        return features
    return {
        "ref": ref,
        "signal": signal.value,
        "kind": "rate" if signal in RATE_SIGNALS else "cap",
        "observed": anomaly.observed_value,
        "usual": anomaly.usual_value,
        "threshold": anomaly.threshold,
        "times_usual": _ratio(anomaly.observed_value, anomaly.usual_value),
        "times_threshold": _ratio(anomaly.observed_value, anomaly.threshold),
        "ongoing": anomaly.ended_at is None,
        "minutes_flagged": int((anomaly.last_observed_at - anomaly.started_at).total_seconds() // 60),
    }


def _ratio(value: float, base: float | None) -> float | None:
    if base is None or base <= 0:
        return None
    return value / base


def _classification(ref: str, answers: Mapping[str, Answer]) -> Classification:
    unusual = answers[f"{ref}_unusual"]
    category = answers[f"{ref}_category"]
    severity = answers[f"{ref}_severity"]
    if (
        not isinstance(unusual, YesNoAnswer)
        or not isinstance(category, ChoiceAnswer)
        or not isinstance(severity, ScoreAnswer)
    ):
        raise ValueError(f"Unexpected answer types for {ref}")
    return Classification(
        unusual_probability=unusual.probability,
        category=category.choice,
        severity=severity.score,
        details={
            "unusual_probability": unusual.probability,
            "category": category.choice,
            "category_confidence": category.confidence,
            "category_probabilities": dict(category.probabilities),
            "severity_level": severity.level,
            "severity_score": severity.score,
            "severity_confidence": severity.confidence,
            "severity_probabilities": dict(severity.probabilities),
        },
    )
