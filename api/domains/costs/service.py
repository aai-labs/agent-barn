import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.costs.models import (
    AgentCostRead,
    AgentModelBreakdown,
    AgentSpendSeriesPoint,
    CostFilter,
    CostFilterOption,
    CostHistogramBucket,
    CostRecord,
    CostRecordRead,
    CostRecordSource,
    CostSeriesPoint,
    CostSummaryRead,
    TokenSeriesPoint,
)
from api.domains.costs.repository import CostRepository
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class CostService:
    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    repository: CostRepository

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    # --- Org cost surface --------------------------------------------------
    #
    # These read our own cost_record table, not LiteLLM. Reading the proxy at request
    # time meant a failed query rendered as a confident $0.00, corrected figures had
    # nowhere to live, and server-side filtering was impossible because the endpoint
    # it used is not paginated.

    def _authorized_org(self, context: CurrentUserContext) -> UUID:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(
            context,
            org_id,
            PermissionKey.COST_READ,
            detail="You don't have permission to view organization costs.",
        )
        return org_id

    def _scoped(self, org_id: UUID, filters: CostFilter) -> CostFilter:
        """Pin the filter to this organization.

        Set here rather than taken from the query string: a caller must never be able
        to widen their own scope by passing an organization_id.
        """
        return filters.model_copy(update={"organization_id": org_id})

    def get_org_cost_summary(
        self,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
    ) -> CostSummaryRead:
        scoped = self._scoped(self._authorized_org(context), filters)
        return build_cost_summary(self.repository, window, scoped)

    def list_org_costs(
        self,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedItems[CostRecordRead]:
        scoped = self._scoped(self._authorized_org(context), filters)
        found = self.repository.find_paginated(window, scoped, Pagination(page=page, size=page_size))
        return PaginatedItems(
            page=found.page,
            page_size=found.page_size,
            total=found.total,
            items=[_to_cost_record_read(record) for record in found.items],
        )

    def list_org_agent_options(
        self,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[CostFilterOption]:
        scoped = self._scoped(self._authorized_org(context), filters)
        return [
            CostFilterOption(value=str(agent_id), label=name or "Unnamed agent")
            for agent_id, name, _org_name in self.repository.distinct_agents(window, scoped)
        ]

    def list_org_model_options(
        self,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[CostFilterOption]:
        scoped = self._scoped(self._authorized_org(context), filters)
        return [
            CostFilterOption(value=model, label=model.split("/")[-1])
            for model in self.repository.distinct_models(window, scoped)
        ]

    def get_agent_cost(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
    ) -> AgentCostRead:
        """Spend for one agent over the requested window.

        Previously read LiteLLM's /key/info, which reports a key's lifetime spend and
        ignores the date range entirely — so this endpoint answered a different
        question from the one it was asked. Reading our own table fixes that, and
        keeps working after the agent's key has been deleted.
        """
        try:
            agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.COST_READ)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            # Implicit Organization Owner/Admin authority retains historical spend
            # access after soft deletion. Explicit Agent assignments never do.
            cost_scope = self.agent_authorization.require_collection_scope(
                context,
                PermissionKey.COST_READ,
            )
            agent = self.agent_repository.get_deleted_in_scope(agent_id, cost_scope)
            if agent is None:
                raise

        filters = CostFilter(organization_id=agent.organization_id, agent_id=agent.id)
        totals = self.repository.totals(window, filters)
        breakdown = self.repository.model_breakdown(window, filters)

        return AgentCostRead(
            agent_id=agent.id,
            agent_name=agent.name,
            model=agent.model,
            status=_display_status(agent),
            total_cost=float(totals.spend),
            total_tokens=totals.prompt_tokens + totals.completion_tokens,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            models_breakdown=[
                AgentModelBreakdown(
                    model=model,
                    total_cost=float(spend),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                for model, spend, prompt_tokens, completion_tokens in breakdown
            ],
        )


def _display_status(agent: Agent) -> str:
    if agent.deleted_at is not None:
        return "deleted"
    status_map = {"RUNNING": "active", "STOPPED": "stopped", "ERROR": "error"}
    return status_map.get(agent.status.value, "unknown")


def _to_cost_record_read(record: CostRecord) -> CostRecordRead:
    return CostRecordRead(
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
    )


def build_cost_summary(
    repository: CostRepository,
    window: StatsWindow,
    scoped: CostFilter,
) -> CostSummaryRead:
    """The stat cards and charts, built from one filter.

    A free function rather than a method: the org and platform surfaces build the
    identical summary from the identical predicate, and the only difference between
    them is what the filter is allowed to say.
    """
    totals = repository.totals(window, scoped)
    top = repository.top_model(window, scoped)
    return CostSummaryRead(
        period=window.period,
        from_date=window.start,
        to_date=window.end,
        granularity=window.granularity,
        total_spend=float(totals.spend),
        total_calls=totals.calls,
        active_agents=totals.agents,
        top_model=top[0] if top else None,
        top_model_spend=float(top[1]) if top else 0.0,
        avg_cost_per_call=float(totals.spend) / totals.calls if totals.calls else 0.0,
        avg_prompt_tokens=totals.avg_prompt_tokens,
        spend_over_time=[
            CostSeriesPoint(bucket=bucket, spend=float(spend), calls=calls)
            for bucket, spend, calls in repository.spend_series(window, scoped)
        ],
        avg_prompt_tokens_over_time=[
            TokenSeriesPoint(bucket=bucket, avg_prompt_tokens=value)
            for bucket, value in repository.avg_prompt_tokens_series(window, scoped)
        ],
        spend_by_agent_over_time=[
            AgentSpendSeriesPoint(bucket=bucket, agent_id=agent_id, agent_name=name, spend=float(spend))
            for bucket, agent_id, name, spend in repository.spend_by_agent_series(window, scoped)
        ],
        cost_per_call_histogram=[
            CostHistogramBucket(
                lower=float(lower),
                upper=float(upper) if upper is not None else None,
                calls=calls,
            )
            for lower, upper, calls in repository.cost_per_call_histogram(window, scoped)
        ],
    )
