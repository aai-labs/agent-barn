"""Charges an Organization's LiteLLM team does not count: historical shared-key memory
charges, and, on credit, calls whose cost only healing found."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from injector import inject

from api.core.config import Config
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW


@inject
@dataclass
class MemoryBudgetAccounting:
    costs: CostRepository
    config: Config

    def spend_outside_team(self, organization: Organization) -> float:
        """What the Organization spent that its team's own spend leaves out, so limits
        pushed to the team are lowered by it and spend read from the team is raised."""
        return self.legacy_spend(organization) + self.healed_spend(organization)

    def healed_spend(self, organization: Organization) -> float:
        """On credit only: everything granted is spent down once, so a cost the team never
        counted would be free credit. A renewing limit lets a missed cost go with the
        period it fell in."""
        if organization.llm_budget_duration != ONE_OFF_BUDGET_WINDOW:
            return 0.0
        return float(
            self.costs.healed_spend(
                organization.id,
                organization.created_at,
                exclude_memory_key_hashes=self.config.memory_cost_key_hashes or frozenset(),
            )
        )

    def legacy_spend(self, organization: Organization) -> float:
        if not self.config.memory_cost_key_hashes:
            return 0.0
        now = datetime.now(UTC)
        if organization.llm_budget_duration == ONE_OFF_BUDGET_WINDOW:
            # A one-off limit never renews: everything since the Organization began counts.
            start = organization.created_at
        else:
            renewal = organization.llm_budget_renews_at
            duration = re.fullmatch(r"([1-9][0-9]*)([smhd])", organization.llm_budget_duration or "")
            if renewal is None or duration is None:
                return 0.0
            renewal = renewal.replace(tzinfo=UTC) if renewal.tzinfo is None else renewal.astimezone(UTC)
            if renewal <= now:
                return 0.0
            seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[duration.group(2)]
            start = renewal - timedelta(seconds=int(duration.group(1)) * seconds)
        return float(
            self.costs.memory_spend(organization.id, start, now, key_hashes=self.config.memory_cost_key_hashes)
        )
