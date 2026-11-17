from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.tiers.models import FREE_TIER_KEY, TierUpdate
from api.domains.tiers.repository import TierRepository
from api.domains.tiers.service import TierService
from api.domains.usage.plans import TrialTermsEditor


@inject
@singleton
@dataclass
class FreeTierTrialTerms(TrialTermsEditor):
    """The trial's terms are the Free Tier's: an edit of them is an edit of Free in the
    catalog, as if made there."""

    catalog: TierService
    repository: TierRepository

    def change(self, changes: Mapping[str, float | int], context: CurrentUserContext) -> None:
        update: dict[str, object] = {}
        if "credit_usd" in changes:
            update["one_time_credit_usd"] = Decimal(str(changes["credit_usd"]))
        if "agent_limit" in changes:
            update["agent_limit"] = changes["agent_limit"]
        if update:
            self.catalog.update_tier(
                self.repository.system_tier_id(FREE_TIER_KEY), TierUpdate.model_validate(update), context
            )
