from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.subscriptions.provider import SubscriptionProviders
from api.domains.tiers.models import FREE_TIER_KEY, NONE_TIER_KEY, Tier
from api.domains.tiers.repository import TierRepository
from api.domains.usage.models import TierActivation
from api.domains.usage.plans import OrganizationPlans, TrialTerms


@inject
@singleton
@dataclass
class TierPlans(OrganizationPlans):
    """The Tier catalog's answers: the trial is Free, and an Organization that pays its own
    way starts on none while a paid Tier can be bought."""

    repository: TierRepository
    subscription_providers: SubscriptionProviders

    def offered_keys(self) -> set[str]:
        return {tier.key for tier in self.repository.list_offered() if tier.activation != TierActivation.NONE}

    def is_trial_plan(self, key: str) -> bool:
        return key == FREE_TIER_KEY

    def trial_plan_id(self) -> UUID:
        return self.repository.system_tier_id(FREE_TIER_KEY)

    def plan_for_paying_organization(self) -> UUID | None:
        if not self.subscription_providers.paid_tiers_purchasable():
            return None
        return self.repository.system_tier_id(NONE_TIER_KEY)

    def trial_terms(self, session: Session, *, for_update: bool = False) -> TrialTerms | None:
        free = self._free(session, for_update=for_update)
        if free is None:
            return None
        return TrialTerms(credit_usd=free.one_time_credit_usd, agent_limit=free.agent_limit, offered=free.enabled)

    def store_trial_terms(self, session: Session, credit_usd: Decimal, agent_limit: int, now: datetime) -> None:
        free = self._free(session, for_update=True)
        if free is None:
            return
        free.one_time_credit_usd = credit_usd
        free.agent_limit = agent_limit
        free.updated_at = now
        session.add(free)

    @staticmethod
    def _free(session: Session, *, for_update: bool) -> Tier | None:
        query = select(Tier).where(col(Tier.activation) == TierActivation.FREE)
        return session.exec(query.with_for_update() if for_update else query).first()
