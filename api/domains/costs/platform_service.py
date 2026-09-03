import logging
from dataclasses import dataclass

from injector import inject, singleton

from api.domains.costs.models import (
    CostFilter,
    CostFilterOption,
    CostRecord,
    CostRecordSource,
    OrganizationSpendRead,
    PlatformCostRecordRead,
    PlatformCostSummaryRead,
)
from api.domains.costs.repository import CostRepository
from api.domains.costs.service import build_cost_summary
from api.domains.platform_admin.models import StatsWindow
from api.infrastructure.openrouter.client import OpenRouterClient
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400


@inject
@singleton
@dataclass
class PlatformCostService:
    """Platform-wide cost reads.

    A separate service from CostService, and a separate read model from the org one,
    per the oversight ADR's dedicated-read-model rule: the org surface must have no
    code path that can return another organization's name or spend, even by mistake.
    Authorization is the route's `require_platform_admin`; nothing here re-scopes by
    membership, because a platform admin deliberately has no membership.
    """

    repository: CostRepository
    openrouter: OpenRouterClient

    def get_summary(self, window: StatsWindow, filters: CostFilter) -> PlatformCostSummaryRead:
        base = build_cost_summary(self.repository, window, filters)
        unattributed_spend, unattributed_calls = self.repository.unattributed_totals(window, filters)
        organizations = self.repository.spend_by_organization(window, filters)

        window_days = (window.end - window.start).total_seconds() / _SECONDS_PER_DAY
        daily_burn = base.total_spend / window_days if window_days > 0 else 0.0
        credits = self.openrouter.get_credits_remaining()

        return PlatformCostSummaryRead(
            **base.model_dump(),
            daily_burn_rate=daily_burn,
            credits_remaining=credits,
            runway_days=(credits / daily_burn) if credits is not None and daily_burn > 0 else None,
            unattributed_spend=float(unattributed_spend),
            unattributed_calls=unattributed_calls,
            organizations=[
                OrganizationSpendRead(
                    organization_id=org_id,
                    organization_name=name,
                    spend=float(spend),
                    calls=calls,
                    agents=agents,
                )
                for org_id, name, spend, calls, agents in organizations
            ],
        )

    def list_costs(
        self,
        window: StatsWindow,
        filters: CostFilter,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedItems[PlatformCostRecordRead]:
        found = self.repository.find_paginated(window, filters, Pagination(page=page, size=page_size))
        return PaginatedItems(
            page=found.page,
            page_size=found.page_size,
            total=found.total,
            items=[_to_platform_read(record) for record in found.items],
        )

    def list_organizations(self, window: StatsWindow, filters: CostFilter) -> list[OrganizationSpendRead]:
        return [
            OrganizationSpendRead(
                organization_id=org_id,
                organization_name=name,
                spend=float(spend),
                calls=calls,
                agents=agents,
            )
            for org_id, name, spend, calls, agents in self.repository.spend_by_organization(window, filters)
        ]

    def list_agent_options(self, window: StatsWindow, filters: CostFilter) -> list[CostFilterOption]:
        """Agent options, labelled "agent in organization".

        The organization filter narrows this list rather than sitting beside it, so
        picking an org and then opening the agent filter offers only that org's
        agents instead of every agent on the platform.
        """
        return [
            CostFilterOption(value=str(agent_id), label=_agent_label(name, organization_name))
            for agent_id, name, organization_name in self.repository.distinct_agents(window, filters)
        ]

    def list_model_options(self, window: StatsWindow, filters: CostFilter) -> list[CostFilterOption]:
        return [
            CostFilterOption(value=model, label=model.split("/")[-1])
            for model in self.repository.distinct_models(window, filters)
        ]


def _agent_label(agent_name: str | None, organization_name: str | None) -> str:
    name = agent_name or "Unnamed agent"
    return f"{name} in {organization_name}" if organization_name else name


def _to_platform_read(record: CostRecord) -> PlatformCostRecordRead:
    return PlatformCostRecordRead(
        request_id=record.request_id,
        occurred_at=record.occurred_at,
        spend=float(record.spend),
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        model=record.model,
        status=record.status,
        request_duration_ms=record.request_duration_ms,
        agent_id=record.agent_id,
        agent_name=record.agent_name,
        healed=record.source == CostRecordSource.OPENROUTER_BACKFILL,
        organization_id=record.organization_id,
        organization_name=record.organization_name,
    )
