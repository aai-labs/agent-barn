from uuid import uuid4

import pytest

from api.domains.communications.agentbarn_telegram_rate_limit import TelegramRateLimiter

_ACME = uuid4()
_GLOBEX = uuid4()


def _limiter(*, bot_per_second: float = 25, organization_per_second: float = 5) -> TelegramRateLimiter:
    return TelegramRateLimiter(bot_per_second=bot_per_second, organization_per_second=organization_per_second)


def test_an_organization_may_burst_up_to_its_budget_then_waits() -> None:
    limiter = _limiter(organization_per_second=5)

    allowed = [limiter.acquire(_ACME, now=0.0) for _ in range(5)]
    refused = limiter.acquire(_ACME, now=0.0)

    assert allowed == [0.0] * 5
    assert refused == pytest.approx(0.2)


def test_an_organizations_budget_refills_over_time() -> None:
    limiter = _limiter(organization_per_second=5)
    for _ in range(5):
        limiter.acquire(_ACME, now=0.0)

    assert limiter.acquire(_ACME, now=0.2) == 0.0
    assert limiter.acquire(_ACME, now=0.2) > 0


def test_one_busy_organization_does_not_use_up_anothers_budget() -> None:
    limiter = _limiter(organization_per_second=5)
    for _ in range(10):
        limiter.acquire(_ACME, now=0.0)

    assert limiter.acquire(_GLOBEX, now=0.0) == 0.0


def test_all_organizations_together_stay_within_the_bots_budget() -> None:
    limiter = _limiter(bot_per_second=3, organization_per_second=5)
    organizations = [uuid4() for _ in range(4)]

    results = [limiter.acquire(organization, now=0.0) for organization in organizations]

    assert results[:3] == [0.0, 0.0, 0.0]
    assert results[3] == pytest.approx(1 / 3)


def test_a_refused_call_uses_no_budget() -> None:
    # Refusals happen while the bot is at its limit; they must not push it further over.
    limiter = _limiter(bot_per_second=1, organization_per_second=5)
    limiter.acquire(_ACME, now=0.0)
    for _ in range(10):
        limiter.acquire(_GLOBEX, now=0.0)

    assert limiter.acquire(_GLOBEX, now=1.0) == 0.0
