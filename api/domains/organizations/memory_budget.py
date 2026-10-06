"""Memory spend against the Organization's LLM budget (AF-338).

Memory model calls run on Honcho's single LiteLLM key, which belongs to no team, so
the team budget neither sees nor caps them, and LiteLLM offers no way to add spend
to a team. This pass works on the other side of the inequality instead: it measures
each Organization's memory spend this window and lowers the team's ceiling by that
much, so the proxy refuses agents once agents + memory reach the limit. It also
suspends the Organization's memory at that point, since the Honcho key keeps
spending regardless of the ceiling.

Soft by construction: the ceiling and the suspension are only as fresh as the last
pass, so the schedule bounds the overshoot.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from api.core.config import get_config
from api.domains.costs.service import CostService
from api.domains.organizations.llm_budget_service import parse_timestamp
from api.domains.organizations.models import Organization, budget_window_start
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import LiteLLMClient

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@inject
@dataclass
class OrganizationMemoryBudgetService:
    organization_repository: OrganizationRepository
    litellm: LiteLLMClient
    memory_costs: CostService

    def enforce_memory_budgets(self) -> None:
        config = get_config()
        if not (config.litellm_base_url and config.litellm_secret_name):
            return
        now = _now()
        # Windows snap to calendar boundaries, so Organizations on the same window
        # share a start and the apportionment is read once per start, not per row.
        memory_by_start: dict[datetime, dict[UUID, float]] = {}
        organizations = self.organization_repository.list_capped_organizations()
        failures = 0
        for organization in organizations:
            try:
                self._enforce_one(organization, now, memory_by_start, config.llm_memory_suspend_percent)
            except Exception:
                # One unreadable Organization must not cost every other one its pass.
                failures += 1
                logger.exception("LLM memory budget enforcement failed for Organization %s", organization.id)
        logger.info(
            "LLM memory budgets enforced (%s organizations, %s failed)", len(organizations) - failures, failures
        )

    def _enforce_one(
        self,
        organization: Organization,
        now: datetime,
        memory_by_start: dict[datetime, dict[UUID, float]],
        suspend_percent: int,
    ) -> None:
        status_ = self.litellm.get_team_budget_status(str(organization.id))
        renews_at = parse_timestamp(status_.get("renews_at")) if status_ else None
        if status_ is None or status_.get("spend") is None or renews_at is None:
            # "Could not read it" is not "nothing spent", and without the window
            # there is nothing to measure memory against: leave the row alone.
            return
        agent_spend = float(status_["spend"])

        start = budget_window_start(renews_at, organization.llm_budget_duration)
        if start not in memory_by_start:
            memory_by_start[start] = self.memory_costs.memory_cost_by_organization(start, now)
        memory_spend = memory_by_start[start].get(organization.id, 0.0)

        organization.llm_budget_renews_at = renews_at
        suspended_key = organization.llm_memory_suspended_key if organization.llm_memory_suspended else None
        limit = organization.effective_llm_budget_usd
        if suspended_key is None and agent_spend + memory_spend >= limit * suspend_percent / 100:
            suspended_key = organization.llm_budget_window_key

        stored = self.organization_repository.record_memory_budget(
            organization.id,
            memory_spend_usd=memory_spend,
            observed_at=now,
            renews_at=renews_at,
            suspended_key=suspended_key,
        )
        if stored is None:
            return  # deleted mid-pass
        # Pushed from the fresh row: a limit changed since this pass read the list
        # is honoured rather than overwritten.
        self.litellm.apply_team_budget(str(stored.id), stored.enforced_llm_budget_usd, stored.llm_budget_duration)
