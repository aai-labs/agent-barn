import pytest
from hamcrest import assert_that, close_to, equal_to, has_properties, is_, none

from api.domains.anomalies.detection import (
    MIN_ACTIVE_DAYS,
    RATE_FLOORS,
    RateSignal,
    Sensitivity,
    error_rate,
    evaluate_cap,
    evaluate_rate,
    has_enough_history,
    rate_baseline,
)


def test_baseline_is_the_median_and_scaled_mad_of_active_hours():
    baseline = rate_baseline([10, 12, 11, 13, 50])

    assert_that(baseline, has_properties(median=12, spread=close_to(1.4826, 1e-4), active_hours=5))


def test_an_agent_with_no_active_hours_has_no_baseline():
    assert_that(rate_baseline([]), is_(none()))


def test_a_spike_well_above_the_usual_rate_is_flagged():
    baseline = rate_baseline([100, 110, 90, 105, 95, 100])

    verdict = evaluate_rate(RateSignal.TOOL_CALLS_PER_HOUR, 400, baseline, Sensitivity.NORMAL)

    assert_that(verdict, has_properties(flagged=True, usual=100, observed=400))


def test_ordinary_variation_is_not_flagged():
    baseline = rate_baseline([100, 110, 90, 105, 95, 100])

    verdict = evaluate_rate(RateSignal.TOOL_CALLS_PER_HOUR, 115, baseline, Sensitivity.NORMAL)

    assert_that(verdict.flagged, is_(False))


def test_tiny_numbers_never_flag_even_when_the_baseline_is_zero():
    # An agent that is mostly idle: median 0, MAD 0.
    baseline = rate_baseline([0, 0, 0, 0, 1])
    floor = RATE_FLOORS[RateSignal.TOOL_CALLS_PER_HOUR].min_value

    verdict = evaluate_rate(RateSignal.TOOL_CALLS_PER_HOUR, floor - 1, baseline, Sensitivity.HIGH)

    assert_that(verdict.flagged, is_(False))


def test_a_perfectly_steady_agent_still_tolerates_small_changes():
    baseline = rate_baseline([200] * 20)

    verdict = evaluate_rate(RateSignal.LLM_CALLS_PER_HOUR, 220, baseline, Sensitivity.NORMAL)

    assert_that(verdict.flagged, is_(False))


@pytest.mark.parametrize(
    ("sensitivity", "flagged"),
    [(Sensitivity.LOW, False), (Sensitivity.NORMAL, False), (Sensitivity.HIGH, True)],
)
def test_sensitivity_sets_how_far_above_usual_counts(sensitivity: Sensitivity, flagged: bool):
    # median 100, spread 14.826 -> high flags above ~137, normal ~152, low ~174
    baseline = rate_baseline([90, 100, 110, 90, 100, 110, 100])

    verdict = evaluate_rate(RateSignal.TOOL_CALLS_PER_HOUR, 145, baseline, sensitivity)

    assert_that(verdict.flagged, is_(flagged))


def test_the_threshold_is_reported_with_the_verdict():
    baseline = rate_baseline([90, 100, 110, 90, 100, 110, 100])

    verdict = evaluate_rate(RateSignal.TOOL_CALLS_PER_HOUR, 100, baseline, Sensitivity.NORMAL)

    assert_that(verdict.threshold, close_to(100 + 3.5 * 14.826, 1e-3))


def test_error_rate_needs_enough_calls_to_mean_anything():
    assert_that(error_rate(errors=2, calls=2), is_(none()))


def test_error_rate_is_errors_over_calls():
    assert_that(error_rate(errors=5, calls=20), equal_to(0.25))


def test_an_error_rate_jump_is_flagged():
    baseline = rate_baseline([0.0, 0.05, 0.1, 0.0, 0.05])

    verdict = evaluate_rate(RateSignal.TOOL_ERROR_RATE, 0.8, baseline, Sensitivity.NORMAL)

    assert_that(verdict.flagged, is_(True))


def test_an_error_rate_below_its_floor_is_not_flagged():
    baseline = rate_baseline([0.0, 0.0, 0.0, 0.0])
    floor = RATE_FLOORS[RateSignal.TOOL_ERROR_RATE].min_value

    verdict = evaluate_rate(RateSignal.TOOL_ERROR_RATE, floor - 0.01, baseline, Sensitivity.HIGH)

    assert_that(verdict.flagged, is_(False))


@pytest.mark.parametrize(("active_days", "enough"), [(0, False), (MIN_ACTIVE_DAYS - 1, False), (MIN_ACTIVE_DAYS, True)])
def test_agents_need_activity_on_enough_days_before_anything_flags(active_days: int, enough: bool):
    assert_that(has_enough_history(active_days), is_(enough))


def test_a_cap_fires_when_the_observed_value_exceeds_it():
    assert_that(evaluate_cap(observed=1_001, cap=1_000), has_properties(flagged=True, threshold=1_000))


def test_a_cap_does_not_fire_at_exactly_the_cap():
    assert_that(evaluate_cap(observed=1_000, cap=1_000).flagged, is_(False))
