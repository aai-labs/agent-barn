from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from injector import ProviderOf, inject, singleton
from sqlmodel import Session, col, select

from api.domains.auth.models import CurrentUserContext
from api.domains.subscriptions.provider import SubscriptionProviders
from api.domains.tiers.models import FREE_TIER_KEY, NONE_TIER_KEY, Tier, TierUpdate
from api.domains.tiers.repository import TierRepository
from api.domains.tiers.service import TierService
from api.domains.usage.models import TierActivation
from api.domains.usage.plans import OrganizationPlans, TrialTerms


@inject
@singleton
@dataclass
class TierPlans(OrganizationPlans):
    """The Tier catalog's answers: the trial is Free, and an Organization that pays its own
    way starts on none while a paid Tier can be bought."""

    repository: TierRepository
    # Resolved when used: the catalog's holds reach Agents, which ask the trial's terms here.
    catalog: ProviderOf[TierService]
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

    def change_trial_terms(self, changes: Mapping[str, float | int], context: CurrentUserContext) -> None:
        """An edit of the Free Tier in the catalog, as if made there."""
        update: dict[str, object] = {}
        if "credit_usd" in changes:
            update["one_time_credit_usd"] = Decimal(str(changes["credit_usd"]))
        if "agent_limit" in changes:
            update["agent_limit"] = changes["agent_limit"]
        if update:
            self.catalog.get().update_tier(
                self.repository.system_tier_id(FREE_TIER_KEY), TierUpdate.model_validate(update), context
            )

    @staticmethod
    def _free(session: Session, *, for_update: bool) -> Tier | None:
        query = select(Tier).where(col(Tier.activation) == TierActivation.FREE)
        return session.exec(query.with_for_update() if for_update else query).first()
