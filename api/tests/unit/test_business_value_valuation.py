from decimal import Decimal

import pytest
from hamcrest import assert_that, equal_to, none

from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.service import (
    WriteCategories,
    categorise,
    effective_minutes,
    value_to_spend_ratio,
    value_usd,
)

STALE_OUTCOME_TYPE = "OUTCOME_REMOVED_FROM_CATALOGUE"


def test_effective_minutes_default_to_the_catalogue_without_overrides():
    assert_that(effective_minutes({}), equal_to(DEFAULT_MINUTES))


def test_an_override_replaces_only_its_own_outcome_type():
    minutes = effective_minutes({OutcomeType.RECORD_CREATED.value: 12})

    assert_that(minutes[OutcomeType.RECORD_CREATED], equal_to(12))
    assert_that(
        {outcome: value for outcome, value in minutes.items() if outcome != OutcomeType.RECORD_CREATED},
        equal_to(
            {outcome: value for outcome, value in DEFAULT_MINUTES.items() if outcome != OutcomeType.RECORD_CREATED}
        ),
    )


def test_an_override_for_an_outcome_type_outside_the_catalogue_is_ignored():
    minutes = effective_minutes({STALE_OUTCOME_TYPE: 30})

    assert_that(minutes, equal_to(DEFAULT_MINUTES))


def test_value_is_minutes_times_the_hourly_rate():
    assert_that(value_usd(90, Decimal("40.00")), equal_to(Decimal(60)))


def test_value_keeps_decimal_precision_until_it_is_emitted():
    assert_that(value_usd(7, Decimal("10.00")), equal_to(Decimal(7) * Decimal("10.00") / 60))


def test_value_is_null_without_an_hourly_rate():
    assert_that(value_usd(90, None), none())


def test_value_is_zero_for_a_zero_rate():
    assert_that(value_usd(90, Decimal("0.00")), equal_to(Decimal(0)))


def test_ratio_is_value_over_spend():
    assert_that(value_to_spend_ratio(Decimal(60), Decimal(15)), equal_to(4.0))


def test_ratio_is_null_without_a_value():
    assert_that(value_to_spend_ratio(None, Decimal(15)), none())


def test_ratio_is_null_when_nothing_was_spent():
    assert_that(value_to_spend_ratio(Decimal(60), Decimal(0)), none())


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            (True, OutcomeType.RECORD_CREATED.value, BusinessActionStatus.SUCCESS, 3),
            WriteCategories(successful={OutcomeType.RECORD_CREATED: 3}, unverified=0, failed=0, unclassified=0),
        ),
        (
            (True, OutcomeType.RECORD_CREATED.value, BusinessActionStatus.UNKNOWN, 3),
            WriteCategories(successful={}, unverified=3, failed=0, unclassified=0),
        ),
        (
            (True, OutcomeType.RECORD_CREATED.value, BusinessActionStatus.ERROR, 3),
            WriteCategories(successful={}, unverified=0, failed=3, unclassified=0),
        ),
        (
            (None, None, BusinessActionStatus.SUCCESS, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=3),
        ),
        (
            (None, None, BusinessActionStatus.ERROR, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=3),
        ),
        (
            (True, None, BusinessActionStatus.SUCCESS, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=3),
        ),
        (
            (True, STALE_OUTCOME_TYPE, BusinessActionStatus.SUCCESS, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=3),
        ),
        (
            (True, STALE_OUTCOME_TYPE, BusinessActionStatus.UNKNOWN, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=3),
        ),
        (
            (False, None, BusinessActionStatus.SUCCESS, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=0),
        ),
        (
            (False, None, BusinessActionStatus.UNKNOWN, 3),
            WriteCategories(successful={}, unverified=0, failed=0, unclassified=0),
        ),
    ],
    ids=[
        "classified-success-is-successful",
        "classified-unknown-is-unverified",
        "classified-error-is-failed",
        "path-outside-catalogue-is-unclassified",
        "path-outside-catalogue-is-unclassified-at-any-status",
        "write-without-outcome-type-is-unclassified",
        "stale-outcome-type-is-unclassified",
        "stale-outcome-type-is-unclassified-at-any-status",
        "read-is-not-counted",
        "unverified-read-is-not-counted",
    ],
)
def test_categorise_places_each_business_action_in_one_category(row, expected):
    assert_that(categorise([row]), equal_to(expected))


def test_categorise_sums_counts_across_rows():
    rows = [
        (True, OutcomeType.RECORD_CREATED.value, BusinessActionStatus.SUCCESS, 2),
        (True, OutcomeType.RECORD_CREATED.value, BusinessActionStatus.SUCCESS, 5),
        (True, OutcomeType.COMMENT_POSTED.value, BusinessActionStatus.SUCCESS, 1),
        (True, OutcomeType.COMMENT_POSTED.value, BusinessActionStatus.UNKNOWN, 4),
        (True, OutcomeType.RECORD_DELETED.value, BusinessActionStatus.ERROR, 6),
        (None, None, BusinessActionStatus.SUCCESS, 7),
        (True, None, BusinessActionStatus.UNKNOWN, 8),
    ]

    assert_that(
        categorise(rows),
        equal_to(
            WriteCategories(
                successful={OutcomeType.RECORD_CREATED: 7, OutcomeType.COMMENT_POSTED: 1},
                unverified=4,
                failed=6,
                unclassified=15,
            )
        ),
    )


def test_categorise_of_nothing_is_empty():
    assert_that(categorise([]), equal_to(WriteCategories(successful={}, unverified=0, failed=0, unclassified=0)))
