from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.activity.models import (
    ActivityBucketRead,
    ActivityFilter,
    ActivityTotals,
    ActivityTrigger,
    ActivityTriggerBreakdown,
    AgentActivityCallRead,
    AgentActivitySummaryRead,
    AgentWakeRead,
    PromptTokenDistribution,
)
from api.domains.activity.repository import ActivityRepository
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.auth.models import CurrentUserContext
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class ActivityService:
    """The Agent's own view of what it has been doing, and what that cost."""

    repository: ActivityRepository
    agent_authorization: AgentAuthorization

    def _require_agent(self, agent_id: UUID, context: CurrentUserContext) -> Agent:
        """Both permissions, because the answer mixes both kinds of fact.

        Every row is a billed call, so `cost.read` applies; the trigger column is
        derived from message timing, so `activity.read` does too. Every Agent
        Access Role grants both, so requiring them together costs no reader
        access it would otherwise have.
        """
        agent = self.agent_authorization.require_visible(context, agent_id)
        self.agent_authorization.require_action_for_visible(context, agent, PermissionKey.COST_READ)
        self.agent_authorization.require_action_for_visible(context, agent, PermissionKey.ACTIVITY_READ)
        return agent

    def get_summary(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
    ) -> AgentActivitySummaryRead:
        agent = self._require_agent(agent_id, context)
        totals = self.repository.call_totals(agent.id, agent.organization_id, window)
        breakdown = self.repository.trigger_breakdown(agent.id, agent.organization_id, window)
        series = self.repository.bucket_series(agent.id, agent.organization_id, window)
        cadence = self.repository.wake_cadence_seconds(agent.id, agent.organization_id, window)

        return AgentActivitySummaryRead(
            agent_id=agent.id,
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            last_call_at=totals.last_call_at,
            totals=ActivityTotals(
                calls=totals.calls,
                wakes=sum(entry.wakes for entry in breakdown),
                spend=float(totals.spend),
                prompt_tokens=totals.prompt_tokens,
                completion_tokens=totals.completion_tokens,
            ),
            prompt_tokens_per_call=PromptTokenDistribution(
                avg=totals.avg_prompt_tokens,
                median=totals.median_prompt_tokens,
                p95=totals.p95_prompt_tokens,
                max=totals.max_prompt_tokens,
            ),
            # Ordered, and both kinds always present: a client rendering a split
            # should show "0 user-triggered" rather than omit the row, which is
            # the very thing worth noticing.
            by_trigger=[
                self._trigger_entry(breakdown, ActivityTrigger.USER),
                self._trigger_entry(breakdown, ActivityTrigger.BACKGROUND),
            ],
            by_bucket=[
                ActivityBucketRead(
                    bucket=bucket,
                    calls=calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    spend=float(spend),
                )
                for bucket, calls, prompt_tokens, completion_tokens, spend in series
            ],
            wake_cadence_seconds=cadence,
        )

    def list_wakes(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: ActivityFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AgentWakeRead]:
        agent = self._require_agent(agent_id, context)
        page = self.repository.find_wakes(agent.id, agent.organization_id, window, filters, pagination)
        return PaginatedItems(
            page=page.page,
            page_size=page.page_size,
            total=page.total,
            items=[
                AgentWakeRead(
                    started_at=row.started_at,
                    ended_at=row.ended_at,
                    trigger=row.trigger,
                    calls=row.calls,
                    spend=float(row.spend),
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    min_prompt_tokens=row.min_prompt_tokens,
                    max_prompt_tokens=row.max_prompt_tokens,
                    models=row.models,
                )
                for row in page.items
            ],
        )

    def list_calls(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
        filters: ActivityFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AgentActivityCallRead]:
        agent = self._require_agent(agent_id, context)
        page = self.repository.find_calls(agent.id, agent.organization_id, window, filters, pagination)
        return PaginatedItems(
            page=page.page,
            page_size=page.page_size,
            total=page.total,
            items=[
                AgentActivityCallRead(
                    request_id=record.request_id,
                    occurred_at=record.occurred_at,
                    model=record.model,
                    status=record.status,
                    spend=float(record.spend),
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    request_duration_ms=record.request_duration_ms,
                )
                for record in page.items
            ],
        )

    @staticmethod
    def _trigger_entry(breakdown, trigger: ActivityTrigger) -> ActivityTriggerBreakdown:
        for entry in breakdown:
            if entry.trigger == trigger:
                return ActivityTriggerBreakdown(
                    trigger=trigger,
                    wakes=entry.wakes,
                    calls=entry.calls,
                    spend=float(entry.spend),
                    prompt_tokens=entry.prompt_tokens,
                )
        return ActivityTriggerBreakdown(trigger=trigger)
