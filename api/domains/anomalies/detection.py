"""Statistics that decide whether an Agent's activity is unusual for that Agent.

Pure functions only: the repository supplies the numbers and the service records
the outcome. Each rate is compared against the Agent's own active hours, because an
Agent idle most of the day would otherwise have a median and spread of zero and
every bit of work would look like a spike.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

# Scales the median absolute deviation to approximate a standard deviation for
# normally distributed data, so the sensitivity multipliers read as "spreads".
MAD_SCALE = 1.4826
# Below this share of the median the spread is not trusted: a perfectly steady
# Agent has a spread of zero and would flag on any change at all.
RELATIVE_MIN_SPREAD = 0.1
MIN_ACTIVE_DAYS = 3
MIN_ERROR_RATE_CALLS = 10
BASELINE_DAYS = 14


class Sensitivity(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


# Spreads above the median that count as unusual. 3.5 is the usual cut-off for a
# robust (median/MAD) z-score; high flags more, low flags less.
SENSITIVITY_SPREADS: dict[Sensitivity, float] = {
    Sensitivity.HIGH: 2.5,
    Sensitivity.NORMAL: 3.5,
    Sensitivity.LOW: 5.0,
}


class RateSignal(StrEnum):
    LLM_TOKENS_PER_HOUR = "LLM_TOKENS_PER_HOUR"
    LLM_CALLS_PER_HOUR = "LLM_CALLS_PER_HOUR"
    TOOL_CALLS_PER_HOUR = "TOOL_CALLS_PER_HOUR"
    TOOL_ERROR_RATE = "TOOL_ERROR_RATE"
    WRITES_PER_HOUR = "WRITES_PER_HOUR"


@dataclass(frozen=True)
class RateFloor:
    # Values at or below this never flag, whatever the baseline.
    min_value: float
    # The smallest spread used, for Agents whose history barely varies.
    min_spread: float


RATE_FLOORS: dict[RateSignal, RateFloor] = {
    RateSignal.LLM_TOKENS_PER_HOUR: RateFloor(min_value=50_000, min_spread=5_000),
    RateSignal.LLM_CALLS_PER_HOUR: RateFloor(min_value=30, min_spread=5),
    RateSignal.TOOL_CALLS_PER_HOUR: RateFloor(min_value=30, min_spread=5),
    RateSignal.TOOL_ERROR_RATE: RateFloor(min_value=0.3, min_spread=0.05),
    RateSignal.WRITES_PER_HOUR: RateFloor(min_value=10, min_spread=2),
}


@dataclass(frozen=True)
class RateBaseline:
    median: float
    spread: float
    active_hours: int


@dataclass(frozen=True)
class Verdict:
    flagged: bool
    observed: float
    threshold: float
    # The Agent's usual value; None for hard caps, which ignore the baseline.
    usual: float | None = None


def rate_baseline(hourly_values: Sequence[float]) -> RateBaseline | None:
    if not hourly_values:
        return None
    median = statistics.median(hourly_values)
    mad = statistics.median(abs(value - median) for value in hourly_values)
    return RateBaseline(median=median, spread=mad * MAD_SCALE, active_hours=len(hourly_values))


def rate_threshold(signal: RateSignal, baseline: RateBaseline, sensitivity: Sensitivity) -> float:
    floor = RATE_FLOORS[signal]
    spread = max(baseline.spread, floor.min_spread, baseline.median * RELATIVE_MIN_SPREAD)
    return max(baseline.median + SENSITIVITY_SPREADS[sensitivity] * spread, floor.min_value)


def evaluate_rate(signal: RateSignal, observed: float, baseline: RateBaseline, sensitivity: Sensitivity) -> Verdict:
    threshold = rate_threshold(signal, baseline, sensitivity)
    return Verdict(flagged=observed > threshold, observed=observed, threshold=threshold, usual=baseline.median)


def evaluate_cap(observed: float, cap: float) -> Verdict:
    return Verdict(flagged=observed > cap, observed=observed, threshold=cap)


def error_rate(errors: int, calls: int) -> float | None:
    """The share of tool calls that failed, or None when there are too few to judge."""
    if calls < MIN_ERROR_RATE_CALLS:
        return None
    return errors / calls


def has_enough_history(active_days: int) -> bool:
    return active_days >= MIN_ACTIVE_DAYS
