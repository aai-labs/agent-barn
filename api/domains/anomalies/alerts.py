"""Which flagged activity Owners and Admins are alerted about.

Pure: the alert handler reads the Anomalies a check started and asks this module
about each one.

Classified activity alerts from MEDIUM severity up, unless the decision model thinks
it is probably fine. Activity it could not classify alerts too: classification most
often fails because the Agent's spend has run out, and a runaway Agent is the one to
hear about. The check classifies right after it records, so an unclassified Anomaly
younger than `CLASSIFICATION_GRACE` may still be in progress, and the handler waits.
"""

from datetime import datetime, timedelta
from enum import StrEnum

from api.domains.anomalies.classification import severity_level
from api.domains.anomalies.models import AgentAnomaly, ClassificationState

# Below this probability that the activity is unusual, a flagged item is more likely
# noise than something to look at. The UI's "Probably fine" badge uses the same value
# (`LIKELY_UNUSUAL` in ui/src/features/anomalies/utils.ts); keep the two together.
LIKELY_UNUSUAL = 0.5
# Severities that stay in the tab without an alert.
QUIET_SEVERITIES = frozenset({"LOW"})
# Long enough for a check's classification (one decision per batch, each up to a
# minute) to finish, so an alert does not go out unclassified while it is still running.
CLASSIFICATION_GRACE = timedelta(minutes=5)


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
