from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import (
    ActivitySeriesPoint,
    ActivityTotalsRead,
    AgentActivityRead,
    AgentValueRead,
    OrganizationActivityRead,
    OrganizationValueRead,
    OutcomeMinutesRead,
    OutcomeTypeValueRead,
    ValueSeriesPoint,
    ValueSettingsRead,
    ValueSettingsUpdate,
    ValueTotalsRead,
)
from api.domains.business_value.repository import (
    HOURLY_RATE_FIELD,
    BusinessActionRepository,
    DeliveryOutcomes,
    ValueActivityRepository,
    ValueSettingsRepository,
)
from api.domains.conversations.repository import ConversationRepository
from api.domains.costs.models import CostFilter
from api.domains.costs.repository import CostRepository
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy

MINUTES_PER_HOUR = 60
CATALOGUE_OUTCOME_TYPES = frozenset(outcome.value for outcome in OutcomeType)
UNATTRIBUTED_AGENT_NAME = "Unattributed"
READ_DENIED_DETAIL = "You don't have permission to view value for this organization."
MANAGE_DENIED_DETAIL = "You don't have permission to manage value settings for this organization."


@dataclass(frozen=True)
class WriteCategories:
    successful: dict[OutcomeType, int] = field(default_factory=dict)
    unverified: int = 0
    failed: int = 0
    unclassified: int = 0


def effective_minutes(overrides: dict[str, int]) -> dict[OutcomeType, int]:
    return {outcome: overrides.get(outcome.value, default) for outcome, default in DEFAULT_MINUTES.items()}


def value_usd(minutes: int, rate: Decimal | None) -> Decimal | None:
    if rate is None:
        return None
    return Decimal(minutes) * rate / MINUTES_PER_HOUR


def value_to_spend_ratio(value: Decimal | None, spend: Decimal) -> float | None:
    if value is None or spend == 0:
        return None
    return float(value / spend)


def per_request(amount: Decimal | int, requests: int) -> float | None:
    if requests == 0:
        return None
    return float(Decimal(amount) / requests)


def handled_rate(succeeded: int, failed: int) -> float | None:
    handled = succeeded + failed
    if handled == 0:
        return None
    return succeeded / handled


def utc_bucket(bucket: datetime) -> datetime:
    if bucket.tzinfo is None:
        return bucket.replace(tzinfo=UTC)
    return bucket.astimezone(UTC)


def activity_figures(requests: int, outcomes: DeliveryOutcomes, tool_calls: int, spend: Decimal) -> dict:
    return {
        "requests": requests,
        "handled_without_failure_rate": handled_rate(outcomes.succeeded, outcomes.dead_lettered + outcomes.unavailable),
        "handled_coverage": outcomes.succeeded + outcomes.dead_lettered + outcomes.unavailable,
        "median_response_seconds": outcomes.median_seconds,
        "response_time_coverage": outcomes.first_attempt,
        "cost_per_request": per_request(spend, requests),
        "tool_calls_per_request": per_request(tool_calls, requests),
    }


def agent_identity(
    agent_id: UUID | None, known_agents: dict[UUID, Agent], cost_name: str | None
) -> tuple[str | None, bool]:
    if agent_id is None:
        return UNATTRIBUTED_AGENT_NAME, False
    agent = known_agents.get(agent_id)
    if agent is None:
        return cost_name, True
    return agent.name, agent.deleted_at is not None


def categorise(rows: Sequence[tuple[bool | None, str | None, BusinessActionStatus, int]]) -> WriteCategories:
    successful: dict[OutcomeType, int] = {}
    unverified = failed = unclassified = 0
    for is_write, outcome_type, status, count in rows:
        if is_write is False:
            continue
        if is_write is None or outcome_type not in CATALOGUE_OUTCOME_TYPES:
            unclassified += count
            continue
        if status == BusinessActionStatus.SUCCESS:
            outcome = OutcomeType(outcome_type)
            successful[outcome] = successful.get(outcome, 0) + count
        elif status == BusinessActionStatus.UNKNOWN:
            unverified += count
        else:
            failed += count
    return WriteCategories(successful=successful, unverified=unverified, failed=failed, unclassified=unclassified)


def _as_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _minutes_for(counts: dict[OutcomeType, int], minutes: dict[OutcomeType, int]) -> int:
    return sum(count * minutes[outcome] for outcome, count in counts.items())


def _catalogue_counts(rows: Sequence[tuple[str | None, int]]) -> dict[OutcomeType, int]:
    counts: dict[OutcomeType, int] = {}
    for outcome_type, count in rows:
        if outcome_type in CATALOGUE_OUTCOME_TYPES:
            outcome = OutcomeType(outcome_type)
            counts[outcome] = counts.get(outcome, 0) + count
    return counts


@inject
@singleton
@dataclass
class BusinessValueService:
    settings_repository: ValueSettingsRepository
    business_action_repository: BusinessActionRepository
    cost_repository: CostRepository
    agent_repository: AgentRepository
    activity_repository: ValueActivityRepository
    conversation_repository: ConversationRepository
    permission_policy: PermissionPolicy
    organization_lookup: OrganizationLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> ValueSettingsRead:
        self._require_read(organization_id, context)
        return self._read_settings(organization_id)

    def get_organization_value(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
    ) -> OrganizationValueRead:
        scope = self._require_read(organization_id, context)
        rate = self.settings_repository.get_hourly_rate(organization_id)
        minutes = effective_minutes(self.settings_repository.get_minute_overrides(organization_id))
        cost_filter = CostFilter(organization_id=organization_id)

        categories = categorise(self.business_action_repository.category_counts(window, scope))
        spend = self.cost_repository.totals(window, cost_filter).spend
        minutes_saved = _minutes_for(categories.successful, minutes)
        value = value_usd(minutes_saved, rate)

        return OrganizationValueRead(
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            totals=ValueTotalsRead(
                successful_writes=sum(categories.successful.values()),
                minutes_saved=minutes_saved,
                value=_as_float(value),
                spend=float(spend),
                value_to_spend_ratio=value_to_spend_ratio(value, spend),
                unverified_writes=categories.unverified,
                failed_writes=categories.failed,
                unclassified_actions=categories.unclassified,
                hourly_rate_usd=_as_float(rate),
            ),
            series=self._series(window, scope, cost_filter, minutes, rate),
            agents=self._agents(organization_id, window, scope, cost_filter, minutes, rate),
            top_outcome_types=self._top_outcome_types(categories.successful, minutes, rate),
        )

    def get_organization_activity(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
        window: StatsWindow,
    ) -> OrganizationActivityRead:
        scope = self._require_read(organization_id, context)
        cost_filter = CostFilter(organization_id=organization_id)
        series = self._requests_series(window, scope)
        tool_calls_by_agent: dict[UUID | None, int] = dict(self.activity_repository.tool_calls_by_agent(window, scope))

        return OrganizationActivityRead(
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            totals=ActivityTotalsRead(
                **activity_figures(
                    sum(point.requests for point in series),
                    self.activity_repository.delivery_outcomes_total(window, scope),
                    sum(tool_calls_by_agent.values()),
                    self.cost_repository.totals(window, cost_filter).spend,
                )
            ),
            requests_series=series,
            agents=self._activity_agents(organization_id, window, scope, cost_filter, tool_calls_by_agent),
        )

    def update_settings(
        self,
        organization_id: UUID,
        data: ValueSettingsUpdate,
        context: CurrentUserContext,
    ) -> ValueSettingsRead:
        self._require_manage(organization_id, context)
        rate_addressed = HOURLY_RATE_FIELD in data.model_fields_set
        if not rate_addressed and not data.outcome_minutes:
            return self._read_settings(organization_id)

        result = self.settings_repository.save_with_event(
            organization_id,
            hourly_rate=data.hourly_rate_usd,
            rate_addressed=rate_addressed,
            outcome_minutes={outcome.value: minutes for outcome, minutes in data.outcome_minutes.items()},
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
            subject_display=self.organization_lookup.get_name(organization_id),
        )
        if result.delivery_ids:
            self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._read_settings(organization_id)

    def _require_read(self, organization_id: UUID, context: CurrentUserContext) -> AuthorizationScope:
        self.permission_policy.require_organization(
            context, organization_id, PermissionKey.COST_READ, detail=READ_DENIED_DETAIL
        )
        return self.permission_policy.require_organization(
            context, organization_id, PermissionKey.ACTIVITY_READ, detail=READ_DENIED_DETAIL
        )

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require_organization(
            context, organization_id, PermissionKey.ORGANIZATION_UPDATE, detail=MANAGE_DENIED_DETAIL
        )

    def _series(
        self,
        window: StatsWindow,
        scope: AuthorizationScope,
        cost_filter: CostFilter,
        minutes: dict[OutcomeType, int],
        rate: Decimal | None,
    ) -> list[ValueSeriesPoint]:
        rows_by_bucket: dict[datetime, list[tuple[str, int]]] = {}
        for bucket, outcome_type, count in self.business_action_repository.successful_counts_by_bucket(window, scope):
            rows_by_bucket.setdefault(bucket, []).append((outcome_type, count))
        points = []
        for bucket, spend, _calls in self.cost_repository.spend_series(window, cost_filter):
            bucket_minutes = _minutes_for(_catalogue_counts(rows_by_bucket.get(bucket, [])), minutes)
            points.append(
                ValueSeriesPoint(
                    bucket=bucket.replace(tzinfo=UTC),
                    minutes_saved=bucket_minutes,
                    value=_as_float(value_usd(bucket_minutes, rate)),
                    spend=float(spend),
                )
            )
        return points

    def _agents(
        self,
        organization_id: UUID,
        window: StatsWindow,
        scope: AuthorizationScope,
        cost_filter: CostFilter,
        minutes: dict[OutcomeType, int],
        rate: Decimal | None,
    ) -> list[AgentValueRead]:
        rows_by_agent: dict[UUID | None, list[tuple[str | None, int]]] = {}
        for agent_id, outcome_type, count in self.business_action_repository.successful_counts_by_agent(window, scope):
            rows_by_agent.setdefault(agent_id, []).append((outcome_type, count))
        spend_by_agent: dict[UUID | None, tuple[str | None, Decimal]] = {
            agent_id: (agent_name, spend)
            for agent_id, agent_name, spend, _calls, _prompt, _completion in self.cost_repository.spend_by_agent(
                window, cost_filter
            )
        }
        known_agents = {agent.id: agent for agent in self.agent_repository.find_all_for_org(organization_id)}

        rows = []
        for agent_id in rows_by_agent.keys() | spend_by_agent.keys():
            counts = _catalogue_counts(rows_by_agent.get(agent_id, []))
            cost_name, spend = spend_by_agent.get(agent_id, (None, Decimal(0)))
            agent_name, agent_deleted = agent_identity(agent_id, known_agents, cost_name)
            agent_minutes = _minutes_for(counts, minutes)
            agent_value = value_usd(agent_minutes, rate)
            rows.append(
                AgentValueRead(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_deleted=agent_deleted,
                    successful_writes=sum(counts.values()),
                    minutes_saved=agent_minutes,
                    value=_as_float(agent_value),
                    spend=float(spend),
                    value_to_spend_ratio=value_to_spend_ratio(agent_value, spend),
                )
            )
        return sorted(
            rows,
            key=lambda row: (-row.minutes_saved, -row.spend, row.agent_id is None, str(row.agent_id)),
        )

    def _requests_series(self, window: StatsWindow, scope: AuthorizationScope) -> list[ActivitySeriesPoint]:
        webhooks = {
            utc_bucket(bucket): count
            for bucket, count in self.activity_repository.webhook_invocations_by_bucket(window, scope)
        }
        return [
            ActivitySeriesPoint(bucket=utc_bucket(bucket), requests=inbound + webhooks.get(utc_bucket(bucket), 0))
            for bucket, inbound, _outbound in self.conversation_repository.daily_direction_counts_since(
                window.start,
                window.end,
                unit=window.granularity,
                organization_id=scope.organization_id,
            )
        ]

    def _activity_agents(
        self,
        organization_id: UUID,
        window: StatsWindow,
        scope: AuthorizationScope,
        cost_filter: CostFilter,
        tool_calls_by_agent: dict[UUID | None, int],
    ) -> list[AgentActivityRead]:
        messages: dict[UUID | None, int] = dict(self.activity_repository.inbound_messages_by_agent(window, scope))
        webhooks: dict[UUID | None, int] = dict(self.activity_repository.webhook_invocations_by_agent(window, scope))
        outcomes: dict[UUID | None, DeliveryOutcomes] = dict(
            self.activity_repository.delivery_outcomes_by_agent(window, scope)
        )
        spend_by_agent: dict[UUID | None, tuple[str | None, Decimal]] = {
            agent_id: (agent_name, spend)
            for agent_id, agent_name, spend, _calls, _prompt, _completion in self.cost_repository.spend_by_agent(
                window, cost_filter
            )
        }
        known_agents = {agent.id: agent for agent in self.agent_repository.find_all_for_org(organization_id)}

        rows = []
        agent_ids: set[UUID | None] = {*messages, *webhooks, *outcomes, *tool_calls_by_agent, *spend_by_agent}
        for agent_id in agent_ids:
            cost_name, spend = spend_by_agent.get(agent_id, (None, Decimal(0)))
            agent_name, agent_deleted = agent_identity(agent_id, known_agents, cost_name)
            figures = activity_figures(
                messages.get(agent_id, 0) + webhooks.get(agent_id, 0),
                outcomes.get(agent_id, DeliveryOutcomes()),
                tool_calls_by_agent.get(agent_id, 0),
                spend,
            )
            rows.append(
                AgentActivityRead(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_deleted=agent_deleted,
                    spend=float(spend),
                    **figures,
                )
            )
        return sorted(
            rows,
            key=lambda row: (-row.requests, -row.spend, row.agent_id is None, str(row.agent_id)),
        )

    @staticmethod
    def _top_outcome_types(
        successful: dict[OutcomeType, int],
        minutes: dict[OutcomeType, int],
        rate: Decimal | None,
    ) -> list[OutcomeTypeValueRead]:
        ranked = sorted(
            successful.items(),
            key=lambda item: (-item[1] * minutes[item[0]], -item[1], item[0].value),
        )
        return [
            OutcomeTypeValueRead(
                outcome_type=outcome,
                successful_writes=count,
                effective_minutes=minutes[outcome],
                minutes_saved=count * minutes[outcome],
                value=_as_float(value_usd(count * minutes[outcome], rate)),
            )
            for outcome, count in ranked
        ]

    def _read_settings(self, organization_id: UUID) -> ValueSettingsRead:
        rate = self.settings_repository.get_hourly_rate(organization_id)
        overrides = self.settings_repository.get_minute_overrides(organization_id)
        effective = effective_minutes(overrides)
        return ValueSettingsRead(
            hourly_rate_usd=float(rate) if rate is not None else None,
            outcome_minutes=[
                OutcomeMinutesRead(
                    outcome_type=outcome,
                    default_minutes=default,
                    override_minutes=overrides.get(outcome.value),
                    effective_minutes=effective[outcome],
                    source="override" if outcome.value in overrides else "default",
                )
                for outcome, default in DEFAULT_MINUTES.items()
            ],
        )
