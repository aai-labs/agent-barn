"""Which plan a new Organization starts on, and the trial's terms.

Sign-up, Organization creation and the trial settings ask here instead of reading the Tier
catalog. The implementation bound to `OrganizationPlans` decides; today that is the Tier
catalog (`api.domains.tiers.plans`), where the trial is the Free Tier.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session


@dataclass(frozen=True)
class TrialTerms:
    credit_usd: Decimal
    agent_limit: int
    # Whether new sign-ups may start the trial at all.
    offered: bool


class OrganizationPlans(ABC):
    @abstractmethod
    def offered_keys(self) -> set[str]:
        """The plans a visitor may ask for when signing up."""

    @abstractmethod
    def is_trial_plan(self, key: str) -> bool:
        """Whether the plan asked for is the trial itself."""

    @abstractmethod
    def trial_plan_id(self) -> UUID:
        """The plan a new trial starts on."""

    @abstractmethod
    def plan_for_paying_organization(self) -> UUID | None:
        """The plan for a new Organization that pays its own way and has no trial: one that
        runs nothing until it subscribes, while a plan can be bought. None when nothing can
        be, so the Organization has no plan and is unrestricted, as before plans existed."""

    @abstractmethod
    def trial_terms(self, session: Session, *, for_update: bool = False) -> TrialTerms | None:
        """The trial's credit, Agent limit and whether it is offered, read in the caller's
        transaction. `for_update` locks them until it ends."""

    @abstractmethod
    def store_trial_terms(self, session: Session, credit_usd: Decimal, agent_limit: int, now: datetime) -> None:
        """Store the trial's credit and Agent limit in the caller's transaction."""
