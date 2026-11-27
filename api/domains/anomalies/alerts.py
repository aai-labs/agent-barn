"""Which flagged activity Owners and Admins are alerted about.

Pure: the alert handler reads the Anomalies a check started and asks this module
about each one.

Classified activity alerts from MEDIUM severity up, unless the decision model thinks
it is probably fine. Activity it could not classify alerts too: classification most
often fails because the Agent's spend has run out, and a runaway Agent is the one to
hear about. The check classifies right after it records, so an unclassified Anomaly
younger than `CLASSIFICATION_GRACE` may still be in progress, and the handler waits.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from api.domains.anomalies.classification import severity_level
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal, ClassificationState

# Below this probability that the activity is unusual, a flagged item is more likely
# noise than something to look at. The UI's "Probably fine" badge uses the same value
# (`LIKELY_UNUSUAL` in ui/src/features/anomalies/utils.ts); keep the two together.
LIKELY_UNUSUAL = 0.5
# Severities that stay in the tab without an alert.
QUIET_SEVERITIES = frozenset({"LOW"})
# Long enough for a check's classification (one decision per batch, each up to a
# minute) to finish, so an alert does not go out unclassified while it is still running.
CLASSIFICATION_GRACE = timedelta(minutes=5)

# What the email calls things: the Unusual activity tab's wording
# (ui/src/features/anomalies/utils.ts), so the email reads like the tab it links to.
SIGNAL_LABELS: dict[str, str] = {
    AnomalySignal.LLM_TOKENS_PER_HOUR: "Model tokens per hour",
    AnomalySignal.LLM_CALLS_PER_HOUR: "Model calls per hour",
    AnomalySignal.TOOL_CALLS_PER_HOUR: "Tool calls per hour",
    AnomalySignal.TOOL_ERROR_RATE: "Failed tool calls",
    AnomalySignal.LLM_ERROR_RATE: "Failed model calls",
    AnomalySignal.WRITES_PER_HOUR: "Changes and deletions per hour",
    AnomalySignal.LLM_TOKENS_CAP: "Over the hourly token cap",
    AnomalySignal.LLM_CALLS_CAP: "Over the hourly model call cap",
    AnomalySignal.NEW_TOOL: "New tool",
    AnomalySignal.NEW_INTEGRATION: "New integration",
    AnomalySignal.NEW_INTEGRATION_ACTION: "New action on an integration",
    AnomalySignal.NEW_DESTINATION: "New destination",
}
CATEGORY_LABELS: dict[str, str] = {
    "RUNAWAY_LOOP": "Runaway loop",
    "FAILING_DEPENDENCY": "Something it relies on is failing",
    "MORE_WORK": "More work than usual",
    "NEW_CAPABILITY": "Expected new use",
    "RISKY_ACTION": "Risky action",
    "OTHER": "Other",
}
PERCENT_SIGNALS = frozenset({AnomalySignal.TOOL_ERROR_RATE, AnomalySignal.LLM_ERROR_RATE})
NOT_CLASSIFIED = "Not classified"


class AlertDecision(StrEnum):
    ALERT = "alert"
    SKIP = "skip"
    # Not classified yet, but it may still be: ask again later.
    WAIT = "wait"


def alert_decision(anomaly: AgentAnomaly, now: datetime) -> AlertDecision:
    if anomaly.classification_state != ClassificationState.CLASSIFIED.value or anomaly.classification_severity is None:
        return AlertDecision.WAIT if now - anomaly.created_at < CLASSIFICATION_GRACE else AlertDecision.ALERT
    if severity_level(anomaly.classification_severity) in QUIET_SEVERITIES:
        return AlertDecision.SKIP
    if is_probably_fine(anomaly):
        return AlertDecision.SKIP
    return AlertDecision.ALERT


def is_probably_fine(anomaly: AgentAnomaly) -> bool:
    probability = (anomaly.classification or {}).get("unusual_probability")
    return isinstance(probability, int | float) and probability < LIKELY_UNUSUAL


@dataclass(frozen=True)
class AlertItem:
    """One flagged item as the email shows it."""

    what: str
    detail: str
    classification: str


def describe(anomaly: AgentAnomaly) -> AlertItem:
    signal = AnomalySignal(anomaly.signal)
    if anomaly.subject is not None:
        detail = anomaly.subject
    else:
        parts = [f"{_value(signal, anomaly.observed_value)} at its highest"]
        if anomaly.usual_value is not None:
            parts.append(f"usually {_value(signal, anomaly.usual_value)}")
        elif anomaly.threshold is not None:
            parts.append(f"cap {_value(signal, anomaly.threshold)}")
        detail = ", ".join(parts)
    return AlertItem(what=SIGNAL_LABELS[signal], detail=detail, classification=_classification(anomaly))


def _classification(anomaly: AgentAnomaly) -> str:
    if (
        anomaly.classification_state != ClassificationState.CLASSIFIED.value
        or anomaly.classification_category is None
        or anomaly.classification_severity is None
    ):
        return NOT_CLASSIFIED
    category = CATEGORY_LABELS.get(anomaly.classification_category, CATEGORY_LABELS["OTHER"])
    return f"{category}, {severity_level(anomaly.classification_severity).lower()} severity"


def _value(signal: AnomalySignal, value: float) -> str:
    # Rounds half up, as the tab does.
    if signal in PERCENT_SIGNALS:
        return f"{math.floor(value * 100 + 0.5)}%"
    return f"{math.floor(value + 0.5):,}"
