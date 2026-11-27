"""Which flagged activity is worth alerting Owners and Admins about (AF-464).

Low severity and probably-fine activity stay in the Unusual activity tab. Activity the
decision model could not classify still alerts, since a failed classification is often
the Agent's spend running out; it waits a few minutes first, because the check may
still be classifying it.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, has_properties

from api.domains.anomalies.alerts import (
    CLASSIFICATION_GRACE,
    LIKELY_UNUSUAL,
    AlertDecision,
    AlertItem,
    alert_decision,
    describe,
)
from api.domains.anomalies.models import AgentAnomaly, AnomalySignal, ClassificationState

CREATED = datetime(2026, 11, 25, 11, 0, tzinfo=UTC)


def _anomaly(severity: float | None = None, probability: float | None = None) -> AgentAnomaly:
    classified = severity is not None
    return AgentAnomaly(
        organization_id=uuid4(),
        agent_id=uuid4(),
        signal=AnomalySignal.TOOL_CALLS_PER_HOUR.value,
        observed_value=120,
        started_at=CREATED,
        last_observed_at=CREATED,
        created_at=CREATED,
        classification_state=(ClassificationState.CLASSIFIED if classified else ClassificationState.STATISTICS_ONLY),
        classification_category="RUNAWAY_LOOP" if classified else None,
        classification_severity=severity,
        classification={"unusual_probability": probability} if classified and probability is not None else None,
    )


@pytest.mark.parametrize(("severity", "expected"), [(0.0, "skip"), (1.0, "alert"), (2.0, "alert"), (3.0, "alert")])
def test_classified_activity_alerts_from_medium_severity(severity, expected):
    assert_that(alert_decision(_anomaly(severity, probability=0.9), CREATED), equal_to(AlertDecision(expected)))


def test_a_score_rounding_down_to_low_does_not_alert():
    assert_that(alert_decision(_anomaly(0.49, probability=0.9), CREATED), equal_to(AlertDecision.SKIP))


def test_probably_fine_activity_does_not_alert_however_severe():
    probably_fine = LIKELY_UNUSUAL - 0.01
    assert_that(alert_decision(_anomaly(3.0, probability=probably_fine), CREATED), equal_to(AlertDecision.SKIP))


def test_likely_unusual_activity_at_the_threshold_alerts():
    assert_that(alert_decision(_anomaly(2.0, probability=LIKELY_UNUSUAL), CREATED), equal_to(AlertDecision.ALERT))


def test_a_classification_without_a_probability_is_not_probably_fine():
    assert_that(alert_decision(_anomaly(2.0, probability=None), CREATED), equal_to(AlertDecision.ALERT))


def test_unclassified_activity_waits_while_it_may_still_be_classified():
    almost = CREATED + CLASSIFICATION_GRACE - timedelta(seconds=1)
    assert_that(alert_decision(_anomaly(), almost), equal_to(AlertDecision.WAIT))


def test_unclassified_activity_alerts_once_classification_has_had_its_chance():
    assert_that(alert_decision(_anomaly(), CREATED + CLASSIFICATION_GRACE), equal_to(AlertDecision.ALERT))


def test_a_rate_is_described_by_how_far_it_went_from_usual():
    anomaly = _anomaly(2.0, probability=0.9)
    anomaly.observed_value, anomaly.usual_value = 1234.4, 12.0

    assert_that(
        describe(anomaly),
        equal_to(
            AlertItem(
                what="Tool calls per hour",
                detail="1,234 at its highest, usually 12",
                classification="Runaway loop, high severity",
            )
        ),
    )


def test_an_error_rate_is_described_in_percent():
    anomaly = _anomaly(2.0)
    anomaly.signal, anomaly.observed_value, anomaly.usual_value = AnomalySignal.TOOL_ERROR_RATE.value, 0.62, 0.05

    assert_that(describe(anomaly).detail, equal_to("62% at its highest, usually 5%"))


def test_a_cap_is_described_against_the_cap():
    anomaly = _anomaly(2.0)
    anomaly.signal, anomaly.observed_value, anomaly.threshold = AnomalySignal.LLM_CALLS_CAP.value, 900, 500

    assert_that(describe(anomaly).detail, equal_to("900 at its highest, cap 500"))


def test_a_first_use_is_described_by_what_was_used():
    anomaly = _anomaly(1.0)
    anomaly.signal, anomaly.subject = AnomalySignal.NEW_TOOL.value, "browser_exec"

    assert_that(describe(anomaly), has_properties(what="New tool", detail="browser_exec"))


def test_unclassified_activity_is_described_as_not_classified():
    assert_that(describe(_anomaly()).classification, equal_to("Not classified"))
