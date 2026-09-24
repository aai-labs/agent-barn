from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from hamcrest import assert_that, close_to, contains_exactly, equal_to, has_properties, none

from api.domains.costs.models import CostFilter, resolve_monthly_window
from api.domains.costs.repository import CostRepository, MonthlyTotals
from api.domains.costs.service import build_monthly_costs


def test_the_window_starts_on_the_first_of_the_oldest_month():
    window = resolve_monthly_window(3, now=datetime(2026, 9, 23, 15, 30, tzinfo=UTC))

    assert_that(window.start, equal_to(datetime(2026, 7, 1, tzinfo=UTC)))
    assert_that(window.end, equal_to(datetime(2026, 9, 23, 15, 30, tzinfo=UTC)))


def test_the_window_steps_back_across_a_year_boundary():
    window = resolve_monthly_window(12, now=datetime(2026, 2, 10, tzinfo=UTC))

    assert_that(window.start, equal_to(datetime(2025, 3, 1, tzinfo=UTC)))


def test_one_month_is_just_the_month_in_progress():
    window = resolve_monthly_window(1, now=datetime(2026, 1, 31, 23, 59, tzinfo=UTC))

    assert_that(window.start, equal_to(datetime(2026, 1, 1, tzinfo=UTC)))


class FakeRepository:
    def __init__(self, months: list[MonthlyTotals]):
        self.months = months

    def monthly_totals(self, window, filters):
        return self.months


def _month(month: datetime, spend: str) -> MonthlyTotals:
    return MonthlyTotals(
        month=month,
        spend=Decimal(spend),
        calls=1,
        failed_calls=0,
        prompt_tokens=10,
        completion_tokens=5,
        agents=1,
    )


def test_only_the_month_in_progress_is_projected():
    # Ten days into a thirty-day month, having spent $10: on pace for $30.
    now = datetime(2026, 9, 11, tzinfo=UTC)
    repository = FakeRepository(
        [
            _month(datetime(2026, 8, 1, tzinfo=UTC), "40.00"),
            _month(datetime(2026, 9, 1, tzinfo=UTC), "10.00"),
        ]
    )

    months = build_monthly_costs(
        cast(CostRepository, repository),
        resolve_monthly_window(2, now=now),
        CostFilter(),
    )

    assert_that([month.is_current for month in months], contains_exactly(False, True))
    assert_that(months[0].projected_spend, none())
    assert_that(months[1], has_properties(projected_spend=close_to(30.0, 0.0001)))


def test_december_projects_against_a_thirty_one_day_month():
    now = datetime(2026, 12, 2, 12, tzinfo=UTC)
    repository = FakeRepository([_month(datetime(2026, 12, 1, tzinfo=UTC), "3.00")])

    months = build_monthly_costs(
        cast(CostRepository, repository),
        resolve_monthly_window(1, now=now),
        CostFilter(),
    )

    # 1.5 days elapsed of 31.
    assert_that(months[0], has_properties(projected_spend=close_to(3.0 * 31 / 1.5, 0.0001)))
