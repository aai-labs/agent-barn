from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus

MINUTES_PER_HOUR = 60
CATALOGUE_OUTCOME_TYPES = frozenset(outcome.value for outcome in OutcomeType)


@dataclass(frozen=True)
class WriteCategories:
    successful: dict[OutcomeType, int] = field(default_factory=dict)
    unverified: int = 0
    failed: int = 0
    unclassified: int = 0


def effective_minutes(overrides: dict[str, int]) -> dict[OutcomeType, int]:
    return {outcome: overrides.get(outcome.value, default) for outcome, default in DEFAULT_MINUTES.items()}


def value_usd(minutes: int, rate: Decimal | None) -> Decimal | None:
    if rate is None:
        return None
    return Decimal(minutes) * rate / MINUTES_PER_HOUR


def value_to_spend_ratio(value: Decimal | None, spend: Decimal) -> float | None:
    if value is None or spend == 0:
        return None
    return float(value / spend)


def categorise(rows: Sequence[tuple[bool | None, str | None, BusinessActionStatus, int]]) -> WriteCategories:
    successful: dict[OutcomeType, int] = {}
    unverified = failed = unclassified = 0
    for is_write, outcome_type, status, count in rows:
        if is_write is False:
            continue
        if is_write is None or outcome_type not in CATALOGUE_OUTCOME_TYPES:
            unclassified += count
            continue
        if status == BusinessActionStatus.SUCCESS:
            outcome = OutcomeType(outcome_type)
            successful[outcome] = successful.get(outcome, 0) + count
        elif status == BusinessActionStatus.UNKNOWN:
            unverified += count
        else:
            failed += count
    return WriteCategories(successful=successful, unverified=unverified, failed=failed, unclassified=unclassified)
