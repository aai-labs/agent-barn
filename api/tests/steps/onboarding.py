"""Persisted platform signup policy for onboarding scenarios."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from api.domains.onboarding.models import PlatformTrialSettings
from api.domains.tiers.models import FREE_TIER_KEY, Tier
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def the_free_tier_has(context, *, credit: float | None = None, agent_limit: int | None = None) -> None:
    """The trial's credit or Agent limit, set on the Free Tier as the catalog stores them."""
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        free = session.exec(select(Tier).where(Tier.key == FREE_TIER_KEY)).one()
        if credit is not None:
            free.one_time_credit_usd = Decimal(str(credit))
        if agent_limit is not None:
            free.agent_limit = agent_limit
        session.add(free)
        session.commit()


def trial_settings_are_configured(
    *, enabled: bool = True, credit: float = 10, agent_limit: int = 1, free_offered: bool = True
):
    """Signup as the platform settings and the Free Tier, where its credit and limit live."""

    def step(context):
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            session.add(PlatformTrialSettings(self_signup_enabled=enabled, updated_at=datetime.now(UTC)))
            free = session.exec(select(Tier).where(Tier.key == FREE_TIER_KEY)).one()
            free.one_time_credit_usd = Decimal(str(credit))
            free.agent_limit = agent_limit
            free.enabled = free_offered
            session.add(free)
            session.commit()

    return step
