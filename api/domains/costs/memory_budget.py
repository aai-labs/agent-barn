"""Historical shared-key charges not already included in the Organization team."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from injector import inject

from api.core.config import Config
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import Organization


@inject
@dataclass
class MemoryBudgetAccounting:
    costs: CostRepository
    config: Config

    def legacy_spend(self, organization: Organization) -> float:
        renewal = organization.llm_budget_renews_at
        duration = re.fullmatch(r"([1-9][0-9]*)([smhd])", organization.llm_budget_duration or "")
        if not self.config.memory_cost_key_hashes or renewal is None or duration is None:
            return 0.0
        renewal = renewal.replace(tzinfo=UTC) if renewal.tzinfo is None else renewal.astimezone(UTC)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[duration.group(2)]
        now = datetime.now(UTC)
        if renewal <= now:
            return 0.0
        return float(
            self.costs.memory_spend(
                organization.id,
                renewal - timedelta(seconds=int(duration.group(1)) * seconds),
                now,
                key_hashes=self.config.memory_cost_key_hashes,
            )
        )
