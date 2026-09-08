from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from api.domains.costs.models import CostFilter
from api.domains.costs.platform_service import PlatformCostService
from api.domains.costs.repository import CostRepository, CostTotals
from api.domains.platform_admin.models import StatsGranularity, StatsWindow
from api.infrastructure.openrouter.client import OpenRouterClient

WINDOW = StatsWindow(
    start=datetime(2026, 8, 4, tzinfo=UTC),
    end=datetime(2026, 8, 4, tzinfo=UTC) + timedelta(days=30),
    period=None,
    granularity=StatsGranularity.DAY,
)


class FakeRepository:
    def __init__(self, spend="300.00", calls=100):
        self.spend = Decimal(spend)
        self.calls = calls

    def totals(self, window, filters):
        return CostTotals(spend=self.spend, calls=self.calls, agents=3, avg_prompt_tokens=1000.0)

    def top_model(self, window, filters):
        return ("openrouter/z-ai/glm-5.2", self.spend)

    def spend_series(self, window, filters):
        return []

    def avg_prompt_tokens_series(self, window, filters):
        return []

    def spend_by_agent_series(self, window, filters):
        return []

    def cost_per_call_histogram(self, window, filters):
        return []

    def unattributed_totals(self, window, filters):
        return Decimal(0), 0

    def spend_by_organization(self, window, filters):
        return []


class FakeOpenRouter:
    def __init__(self, credits):
        self.credits = credits

    def get_credits_remaining(self):
        return self.credits


def _summary(*, spend="300.00", calls=100, credits=None):
    # cast: the service takes concrete types because injector resolves it from
    # annotations. These stand in for the two reads the arithmetic below depends on.
    service = PlatformCostService(
        repository=cast(CostRepository, FakeRepository(spend, calls)),
        openrouter=cast(OpenRouterClient, FakeOpenRouter(credits)),
    )
    return service.get_summary(WINDOW, CostFilter())


def test_burn_rate_is_window_spend_divided_by_window_days():
    assert _summary(spend="300.00").daily_burn_rate == 10.0


def test_runway_is_credits_divided_by_burn_rate():
    summary = _summary(spend="300.00", credits=250.0)

    assert summary.credits_remaining == 250.0
    assert summary.runway_days == 25.0


def test_runway_is_unknown_when_credit_is_unknown():
    """None covers both "no credit limit set" and "the poll failed".

    Neither should render as a number: runway is genuinely undefined, and inventing
    a figure on a page about money is worse than admitting the gap.
    """
    summary = _summary(credits=None)

    assert summary.credits_remaining is None
    assert summary.runway_days is None


def test_runway_is_unknown_when_nothing_has_been_spent():
    """Dividing by a zero burn rate would claim infinite runway from no evidence."""
    summary = _summary(spend="0", calls=0, credits=500.0)

    assert summary.daily_burn_rate == 0.0
    assert summary.runway_days is None


def test_a_spent_out_key_reports_no_runway_rather_than_no_answer():
    summary = _summary(spend="300.00", credits=0.0)

    assert summary.credits_remaining == 0.0
    assert summary.runway_days == 0.0
