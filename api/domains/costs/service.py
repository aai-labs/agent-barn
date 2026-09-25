import logging
from dataclasses import dataclass
from datetime import datetime
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
    AgentSpendRead,
    AgentSpendSeriesPoint,
    CostFilter,
    CostFilterOption,
    CostHistogramBucket,
    CostRecord,
    CostRecordRead,
    CostRecordSource,
    CostSeriesPoint,
    CostSummaryRead,
    GroupMemoryCostRead,
    MonthlyCostRead,
    MonthlyWindow,
    TokenSeriesPoint,
    month_start,
)
from api.domains.costs.repository import CostRepository
from api.domains.costs.usage_service import HonchoUsageService
from api.domains.memory_groups.service import MemoryGroupService
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400

# How much of the month in progress must be behind it before its spend is worth
# extrapolating. See `_projected_month_spend`.
MIN_ELAPSED_FOR_PROJECTION_SECONDS = _SECONDS_PER_DAY


@inject
@singleton
@dataclass
class CostService:
    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    repository: CostRepository
    honcho_usage: HonchoUsageService
    memory_groups: MemoryGroupService

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
        org_id = self._authorized_org(context)
        scoped = self._scoped(org_id, filters)
        summary = build_cost_summary(self.repository, window, scoped)
        # Memory spend is billed on Honcho's separate credential, so it is added here
        # rather than coming from the cost_record table the summary reads. It is this
        # Organization's share of the pools — the sum of its groups' apportioned costs,
        # NOT Honcho's platform-wide total (one credential bills every org) — so it
        # reconciles with the per-group rows in memory_cost_by_group.
        cost_by_group = self.honcho_usage.cost_by_group(window.start, window.end)
        summary.total_memory_cost = round(
            sum(cost_by_group.get(str(gid), 0.0) for gid in self.memory_groups.names_for_org(org_id)),
            12,
        )
        return summary

    def memory_cost_by_group(self, context: CurrentUserContext, window: StatsWindow) -> list[GroupMemoryCostRead]:
        """This Organization's memory spend split across its memory groups.

        Memory has no per-Agent attribution (Agents share pools), but the pool is a
        group, so this is the finest split that is meaningful. The figures come from
        apportioning Honcho's authoritative total by per-pool token share, then are
        scoped to the groups this Organization owns and labelled with their names.
        Groups with no memory activity in the window appear with 0, and the rows sum
        to the summary's `total_memory_cost`.
        """
        org_id = self._authorized_org(context)
        cost_by_group = self.honcho_usage.cost_by_group(window.start, window.end)
        names = self.memory_groups.names_for_org(org_id)
        rows = [
            GroupMemoryCostRead(
                group_id=group_id,
                group_name=name,
                memory_cost=round(cost_by_group.get(str(group_id), 0.0), 12),
            )
            for group_id, name in names.items()
        ]
        rows.sort(key=lambda r: (-r.memory_cost, r.group_name.lower()))
        return rows

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

    def list_org_agent_spend(
        self,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[AgentSpendRead]:
        """Every Agent that spent anything in the window, ranked.

        Organization-wide, so it takes the Organization `cost.read` the summary takes
        rather than a per-Agent check: the caller is asking about the whole
        organization's spend, not about one Agent they have been assigned.
        """
        scoped = self._scoped(self._authorized_org(context), filters)
        return [
            AgentSpendRead(
                agent_id=agent_id,
                agent_name=agent_name,
                spend=float(spend),
                calls=calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            for agent_id, agent_name, spend, calls, prompt_tokens, completion_tokens in (
                self.repository.spend_by_agent(window, scoped)
            )
        ]

    def get_org_monthly(
        self,
        context: CurrentUserContext,
        window: MonthlyWindow,
        filters: CostFilter,
    ) -> list[MonthlyCostRead]:
        scoped = self._scoped(self._authorized_org(context), filters)
        return build_monthly_costs(self.repository, window, scoped)

    # --- Agent cost surface ------------------------------------------------
    #
    # Authorized through the effective Agent Access Role rather than the
    # Organization-wide `cost.read`, so an Agent Viewer can read the Agent they were
    # given. Every read pins the filter to that Agent and its Organization.

    def _authorized_agent(self, agent_id: UUID, context: CurrentUserContext) -> Agent:
        try:
            return self.agent_authorization.require_action(context, agent_id, PermissionKey.COST_READ)
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
            return agent

    def _agent_scoped(self, agent: Agent, filters: CostFilter) -> CostFilter:
        return filters.model_copy(update={"organization_id": agent.organization_id, "agent_id": agent.id})

    def get_agent_cost(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter | None = None,
    ) -> AgentCostRead:
        """Spend for one agent over the requested window.

        Previously read LiteLLM's /key/info, which reports a key's lifetime spend and
        ignores the date range entirely — so this endpoint answered a different
        question from the one it was asked. Reading our own table fixes that, and
        keeps working after the agent's key has been deleted.
        """
        agent = self._authorized_agent(agent_id, context)
        scoped = self._agent_scoped(agent, filters or CostFilter())
        totals = self.repository.totals(window, scoped)
        breakdown = self.repository.model_breakdown(window, scoped)
        # Same series builders the organization summary uses; the filter above pins
        # them to this agent, so the trends and the totals beside them describe one
        # set of calls.
        series = self.repository.spend_series(window, scoped)
        spend = float(totals.spend)

        return AgentCostRead(
            agent_id=agent.id,
            agent_name=agent.name,
            model=agent.model,
            status=_display_status(agent),
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            total_cost=spend,
            total_tokens=totals.prompt_tokens + totals.completion_tokens,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            total_calls=totals.calls,
            failed_calls=totals.failed_calls,
            healed_calls=totals.healed_calls,
            avg_cost_per_call=spend / totals.calls if totals.calls else 0.0,
            avg_prompt_tokens=totals.avg_prompt_tokens,
            avg_duration_ms=totals.avg_duration_ms,
            daily_burn_rate=daily_burn_rate(spend, window.start, window.end),
            first_call_at=totals.first_call_at,
            last_call_at=totals.last_call_at,
            # Memory cost is pool-level, not per-Agent (Agents share pools), so the
            # per-Agent view carries no memory figure — see the org summary total.
            memory_cost=0.0,
            models_breakdown=[
                AgentModelBreakdown(
                    model=model,
                    total_cost=float(model_spend),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    calls=calls,
                )
                for model, model_spend, prompt_tokens, completion_tokens, calls in breakdown
            ],
            spend_over_time=[
                CostSeriesPoint(bucket=bucket, spend=float(bucket_spend), calls=calls)
                for bucket, bucket_spend, calls in series
            ],
            avg_prompt_tokens_over_time=[
                TokenSeriesPoint(bucket=bucket, avg_prompt_tokens=value)
                for bucket, value in self.repository.avg_prompt_tokens_series(window, scoped)
            ],
            cost_per_call_histogram=_histogram(self.repository, window, scoped),
        )

    def list_agent_costs(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedItems[CostRecordRead]:
        scoped = self._agent_scoped(self._authorized_agent(agent_id, context), filters)
        found = self.repository.find_paginated(window, scoped, Pagination(page=page, size=page_size))
        return PaginatedItems(
            page=found.page,
            page_size=found.page_size,
            total=found.total,
            items=[_to_cost_record_read(record) for record in found.items],
        )

    def list_agent_model_options(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[CostFilterOption]:
        scoped = self._agent_scoped(self._authorized_agent(agent_id, context), filters)
        return [
            CostFilterOption(value=model, label=model.split("/")[-1])
            for model in self.repository.distinct_models(window, scoped)
        ]

    def get_agent_monthly(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: MonthlyWindow,
        filters: CostFilter,
    ) -> list[MonthlyCostRead]:
        scoped = self._agent_scoped(self._authorized_agent(agent_id, context), filters)
        return build_monthly_costs(self.repository, window, scoped)


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
        cost_per_call_histogram=_histogram(repository, window, scoped),
    )


def _histogram(repository: CostRepository, window: StatsWindow, scoped: CostFilter) -> list[CostHistogramBucket]:
    return [
        CostHistogramBucket(
            lower=float(lower),
            upper=float(upper) if upper is not None else None,
            calls=calls,
        )
        for lower, upper, calls in repository.cost_per_call_histogram(window, scoped)
    ]


def daily_burn_rate(spend: float, start: datetime, end: datetime) -> float:
    """Spend over a span divided by its length in days."""
    days = (end - start).total_seconds() / _SECONDS_PER_DAY
    return spend / days if days > 0 else 0.0


def build_monthly_costs(
    repository: CostRepository,
    window: MonthlyWindow,
    scoped: CostFilter,
) -> list[MonthlyCostRead]:
    """Calendar-month totals, with the month in progress projected to its end.

    Shared by the Agent, Organization and platform surfaces for the same reason
    `build_cost_summary` is: one predicate, three scopes.
    """
    months = repository.monthly_totals(window, scoped)
    current_month = month_start(window.end)
    result = []
    for totals in months:
        spend = float(totals.spend)
        is_current = totals.month == current_month
        result.append(
            MonthlyCostRead(
                month=totals.month,
                spend=spend,
                calls=totals.calls,
                failed_calls=totals.failed_calls,
                prompt_tokens=totals.prompt_tokens,
                completion_tokens=totals.completion_tokens,
                active_agents=totals.agents,
                is_current=is_current,
                projected_spend=_projected_month_spend(spend, totals.month, window.end) if is_current else None,
            )
        )
    return result


def _projected_month_spend(spend: float, month: datetime, now: datetime) -> float | None:
    """Month-to-date spend extrapolated at the pace so far, or None too early to say.

    A straight line, not a forecast: it says where the month lands if nothing
    changes, which is the question a reader of a month-to-date figure is asking.

    It needs a day of the month behind it before it means anything. Half an hour
    into the 1st, the elapsed divisor is about 1/1500th of the month, so five
    cents of spend extrapolates to seventy dollars — and that figure would drive
    "on pace for", the Agent's "This month" card, and the month-over-month change,
    which compares the projection against last month. Below the floor the month
    reports what it has actually spent and no projection at all.
    """
    elapsed = (now - month).total_seconds()
    if elapsed < MIN_ELAPSED_FOR_PROJECTION_SECONDS:
        return None
    length = (month_start(month, 1) - month).total_seconds()
    return spend * length / elapsed
