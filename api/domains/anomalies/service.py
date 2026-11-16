import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.service import AgentService
from api.domains.anomalies.destinations import destination_hosts
from api.domains.anomalies.detection import (
    BASELINE_DAYS,
    RateSignal,
    Sensitivity,
    error_rate,
    evaluate_cap,
    evaluate_rate,
    has_enough_history,
    rate_baseline,
)
from api.domains.anomalies.models import (
    NEW_SIGNAL_BY_KIND,
    AgentAnomalyOverride,
    AgentAnomalyOverrideRead,
    AgentAnomalyOverrideUpdate,
    AnomalyDetectionSettingsRead,
    AnomalyDetectionSettingsUpdate,
    AnomalySignal,
    SeenKind,
)
from api.domains.anomalies.repository import (
    Actor,
    AnomalyRepository,
    AnomalySettingsRepository,
    OverrideValues,
    SeenUse,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.business_value.service import BusinessValueService
from api.domains.costs.service import CostService
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.tool_calls.service import ToolCallService

logger = logging.getLogger(__name__)

READ_DENIED_DETAIL = "You don't have permission to view unusual activity in this organization."
MANAGE_DENIED_DETAIL = "You don't have permission to change how unusual activity is detected."


def override_read(override: AgentAnomalyOverride | None) -> AgentAnomalyOverrideRead:
    if override is None:
        return AgentAnomalyOverrideRead(
            sensitivity=Sensitivity.NORMAL, max_llm_tokens_per_hour=None, max_llm_calls_per_hour=None
        )
    return AgentAnomalyOverrideRead(
        sensitivity=Sensitivity(override.sensitivity),
        max_llm_tokens_per_hour=override.max_llm_tokens_per_hour,
        max_llm_calls_per_hour=override.max_llm_calls_per_hour,
    )


@inject
@singleton
@dataclass
class AnomalyService:
    """Who may see an Agent's Anomalies and adjust its normal: Organization Owners and
    Admins only, through `anomaly.read` and `anomaly.manage`.

    Agent routes resolve the Agent first, so an Agent the caller cannot see is a 404
    before the Organization Permission is checked (as for `agent.size.manage`).
    """

    settings_repository: AnomalySettingsRepository
    permission_policy: PermissionPolicy
    agent_authorization: AgentAuthorization
    organization_lookup: OrganizationLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> AnomalyDetectionSettingsRead:
        self.permission_policy.require(context, organization_id, PermissionKey.ANOMALY_READ, detail=READ_DENIED_DETAIL)
        return self._settings_read(organization_id, context)

    def update_settings(
        self, organization_id: UUID, data: AnomalyDetectionSettingsUpdate, context: CurrentUserContext
    ) -> AnomalyDetectionSettingsRead:
        self.permission_policy.require(
            context, organization_id, PermissionKey.ANOMALY_MANAGE, detail=MANAGE_DENIED_DETAIL
        )
        _settings, delivery_ids = self.settings_repository.set_enabled_with_event(
            organization_id,
            data.enabled,
            actor=self._actor(context, organization_id),
            subject_display=self.organization_lookup.get_name(organization_id),
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return self._settings_read(organization_id, context)

    def set_override(
        self, agent_id: UUID, data: AgentAnomalyOverrideUpdate, context: CurrentUserContext
    ) -> AgentAnomalyOverrideRead:
        agent = self._require_agent(agent_id, context, PermissionKey.ANOMALY_MANAGE, MANAGE_DENIED_DETAIL)
        override, delivery_ids = self.settings_repository.set_override_with_event(
            agent.organization_id,
            agent.id,
            OverrideValues(
                sensitivity=data.sensitivity.value,
                max_llm_tokens_per_hour=data.max_llm_tokens_per_hour,
                max_llm_calls_per_hour=data.max_llm_calls_per_hour,
            ),
            actor=self._actor(context, agent.organization_id),
            subject_display=agent.name,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return override_read(override)

    def _require_agent(
        self, agent_id: UUID, context: CurrentUserContext, permission: PermissionKey, detail: str
    ) -> Agent:
        agent = self.agent_authorization.require_visible(context, agent_id)
        self.permission_policy.require(context, agent.organization_id, permission, detail=detail)
        return agent

    def _settings_read(self, organization_id: UUID, context: CurrentUserContext) -> AnomalyDetectionSettingsRead:
        settings = self.settings_repository.get_settings(organization_id)
        return AnomalyDetectionSettingsRead(
            enabled=settings is not None and settings.enabled,
            can_manage=self.permission_policy.resolve(context, organization_id, PermissionKey.ANOMALY_MANAGE)
            is not None,
            updated_at=settings.updated_at if settings is not None else None,
        )

    @staticmethod
    def _actor(context: CurrentUserContext, organization_id: UUID) -> Actor:
        return Actor(
            identity=resolve_actor_identity(context, organization_id),
            display=context.user.full_name or context.user.email,
        )


# Rows are stamped when inserted but only visible once their transaction commits, so
# the check stops short of "now" to read each row exactly once.
STORAGE_LAG = timedelta(minutes=2)
WINDOW = timedelta(hours=1)
BASELINE = timedelta(days=BASELINE_DAYS)
# Every argument key `destination_hosts` reads, on either runtime.
DESTINATION_ARGUMENT_KEYS = ("url", "urls", "targetUrl", "action", "command")


@dataclass(frozen=True)
class CheckSummary:
    organizations: int
    agents: int
    failures: int


@dataclass
class _History:
    """An Agent's hourly figures over its baseline window and the hour being checked."""

    active_days: int
    tool_calls: list[float]
    error_rates: list[float]
    writes: list[float]
    llm_calls: list[float]
    llm_tokens: list[float]
    observed_tool_calls: int
    observed_errors: int
    observed_writes: int
    observed_llm_calls: int | None
    observed_llm_tokens: int | None


def _floor_hour(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


@inject
@singleton
@dataclass
class AnomalyCheckService:
    """The scheduled check: each Agent of each opted-in Organization against its own
    last fourteen days.

    Background work. It takes Organizations and Agents from persisted rows and reads
    other domains only through their services.
    """

    repository: AnomalyRepository
    settings_repository: AnomalySettingsRepository
    agent_service: AgentService
    tool_call_service: ToolCallService
    cost_service: CostService
    business_value_service: BusinessValueService

    def run_checks(self, now: datetime | None = None) -> CheckSummary:
        until = (now or datetime.now(UTC)) - STORAGE_LAG
        synced = self.cost_service.last_sync_completed_at()
        # LLM figures are complete only up to the last cost sync; without one there
        # are none to judge.
        cost_until = min(until, synced) if synced is not None else None
        organizations = self.repository.enabled_organization_ids()
        agents = failures = 0
        for organization_id in organizations:
            for agent_id in self.agent_service.live_agent_ids(organization_id):
                agents += 1
                try:
                    self._check_agent(organization_id, agent_id, until, cost_until)
                except Exception:
                    failures += 1
                    logger.exception("Anomaly check failed for agent %s", agent_id)
        return CheckSummary(organizations=len(organizations), agents=agents, failures=failures)

    def _check_agent(self, organization_id: UUID, agent_id: UUID, until: datetime, cost_until: datetime | None) -> None:
        override = self.settings_repository.get_override(agent_id)
        sensitivity = Sensitivity(override.sensitivity) if override is not None else Sensitivity.NORMAL
        history = self.history(agent_id, until, cost_until)
        enough = has_enough_history(history.active_days)

        def rate(signal: RateSignal, observed: float | None, values: list[float], at: datetime) -> None:
            baseline = rate_baseline(values)
            verdict = None
            if observed is not None and enough and baseline is not None:
                verdict = evaluate_rate(signal, observed, baseline, sensitivity)
            self._record(organization_id, agent_id, AnomalySignal(signal.value), verdict, at)

        rate(RateSignal.TOOL_CALLS_PER_HOUR, history.observed_tool_calls, history.tool_calls, until)
        rate(
            RateSignal.TOOL_ERROR_RATE,
            error_rate(history.observed_errors, history.observed_tool_calls),
            history.error_rates,
            until,
        )
        rate(RateSignal.WRITES_PER_HOUR, history.observed_writes, history.writes, until)
        if cost_until is not None:
            rate(RateSignal.LLM_CALLS_PER_HOUR, history.observed_llm_calls, history.llm_calls, cost_until)
            rate(RateSignal.LLM_TOKENS_PER_HOUR, history.observed_llm_tokens, history.llm_tokens, cost_until)
            self._check_caps(organization_id, agent_id, override, history, cost_until)
        self._check_first_use(organization_id, agent_id, until, enough)

    def _record(self, organization_id: UUID, agent_id: UUID, signal: AnomalySignal, verdict, at: datetime) -> None:
        if verdict is not None and verdict.flagged:
            self.repository.open_or_update(organization_id, agent_id, signal, verdict, at)
        else:
            self.repository.end_ongoing(agent_id, signal, at)

    def _check_caps(
        self,
        organization_id: UUID,
        agent_id: UUID,
        override: AgentAnomalyOverride | None,
        history: _History,
        at: datetime,
    ) -> None:
        caps = (
            (
                AnomalySignal.LLM_TOKENS_CAP,
                override.max_llm_tokens_per_hour if override else None,
                history.observed_llm_tokens,
            ),
            (
                AnomalySignal.LLM_CALLS_CAP,
                override.max_llm_calls_per_hour if override else None,
                history.observed_llm_calls,
            ),
        )
        for signal, cap, observed in caps:
            verdict = evaluate_cap(observed, cap) if cap is not None and observed is not None else None
            self._record(organization_id, agent_id, signal, verdict, at)

    def history(self, agent_id: UUID, until: datetime, cost_until: datetime | None) -> _History:
        """Hourly figures over the baseline window, which stops at the start of the hour
        the checked hour begins in, so the two never overlap."""
        tool_hours = self.tool_call_service.hourly_tool_activity(
            agent_id, until - BASELINE, _floor_hour(until - WINDOW)
        )
        write_hours = {
            row.hour: row.writes
            for row in self.business_value_service.hourly_writes(
                agent_id, until - BASELINE, _floor_hour(until - WINDOW)
            )
        }
        llm_hours = (
            self.cost_service.hourly_llm_usage(agent_id, cost_until - BASELINE, _floor_hour(cost_until - WINDOW))
            if cost_until is not None
            else []
        )
        tools_by_hour = {row.hour: row for row in tool_hours}
        llm_by_hour = {row.hour: row for row in llm_hours}
        active = sorted(tools_by_hour.keys() | llm_by_hour.keys())

        observed_tools = self.tool_call_service.hourly_tool_activity(agent_id, until - WINDOW, until)
        observed_writes = self.business_value_service.hourly_writes(agent_id, until - WINDOW, until)
        observed_llm = (
            self.cost_service.hourly_llm_usage(agent_id, cost_until - WINDOW, cost_until)
            if cost_until is not None
            else None
        )
        error_rates = [rate for row in tool_hours if (rate := error_rate(row.errors, row.calls)) is not None]
        return _History(
            active_days=len({hour.date() for hour in active}),
            tool_calls=[float(tools_by_hour[hour].calls) if hour in tools_by_hour else 0.0 for hour in active],
            error_rates=error_rates,
            writes=[float(write_hours.get(hour, 0)) for hour in active],
            llm_calls=[float(llm_by_hour[hour].calls) if hour in llm_by_hour else 0.0 for hour in active],
            llm_tokens=[float(llm_by_hour[hour].tokens) if hour in llm_by_hour else 0.0 for hour in active],
            observed_tool_calls=sum(row.calls for row in observed_tools),
            observed_errors=sum(row.errors for row in observed_tools),
            observed_writes=sum(row.writes for row in observed_writes),
            observed_llm_calls=sum(row.calls for row in observed_llm) if observed_llm is not None else None,
            observed_llm_tokens=sum(row.tokens for row in observed_llm) if observed_llm is not None else None,
        )

    def _check_first_use(self, organization_id: UUID, agent_id: UUID, until: datetime, enough: bool) -> None:
        """Flag what the Agent used for the first time in its baseline window.

        An Agent read for the first time (no state) only learns what it already uses,
        from its baseline window, and flags nothing: everything would look new.
        """
        state = self.repository.get_state(agent_id)
        learning = state is None
        tool_calls_after = None if state is None else state.tool_calls_read_through
        actions_after = None if state is None else state.business_actions_read_through
        occurred_since = until - BASELINE if learning else None
        calls = self.tool_call_service.tool_calls_stored_between(
            agent_id,
            after=tool_calls_after,
            until=until,
            argument_keys=DESTINATION_ARGUMENT_KEYS,
            occurred_since=occurred_since,
        )
        actions = self.business_value_service.business_actions_stored_between(
            agent_id, after=actions_after, until=until, occurred_since=occurred_since
        )
        observations: list[tuple[SeenKind, str, datetime]] = []
        for call in calls:
            observations.append((SeenKind.TOOL, call.tool_name, call.occurred_at))
            observations.extend(
                (SeenKind.DESTINATION, host, call.occurred_at)
                for host in sorted(destination_hosts(call.tool_name, call.arguments))
            )
        for action in actions:
            observations.append((SeenKind.INTEGRATION, action.integration, action.occurred_at))
            observations.append(
                (SeenKind.INTEGRATION_ACTION, f"{action.integration} {action.verb}", action.occurred_at)
            )
        uses, counts = _summarise(observations)

        if not learning and enough:
            self._flag_first_uses(organization_id, agent_id, uses, counts)
        self.repository.mark_seen(organization_id, agent_id, uses)
        self.repository.save_state(
            organization_id,
            agent_id,
            tool_calls_read_through=max(until, tool_calls_after or until),
            business_actions_read_through=max(until, actions_after or until),
        )

    def _flag_first_uses(
        self, organization_id: UUID, agent_id: UUID, uses: list[SeenUse], counts: dict[tuple[SeenKind, str], int]
    ) -> None:
        by_kind: dict[SeenKind, list[SeenUse]] = defaultdict(list)
        for use in uses:
            by_kind[use.kind].append(use)
        new_integrations: set[str] = set()
        for kind in (SeenKind.TOOL, SeenKind.DESTINATION, SeenKind.INTEGRATION, SeenKind.INTEGRATION_ACTION):
            kind_uses = by_kind.get(kind, [])
            last_seen = self.repository.last_seen(agent_id, kind, [use.subject for use in kind_uses])
            for use in kind_uses:
                seen_at = last_seen.get(use.subject)
                if seen_at is not None and seen_at >= use.first_at - BASELINE:
                    continue
                if kind is SeenKind.INTEGRATION:
                    new_integrations.add(use.subject)
                # A brand-new integration is one Anomaly, not one more per action on it.
                if kind is SeenKind.INTEGRATION_ACTION and use.subject.split(" ", 1)[0] in new_integrations:
                    continue
                self.repository.record_first_use(
                    organization_id,
                    agent_id,
                    NEW_SIGNAL_BY_KIND[kind],
                    use.subject,
                    use.first_at,
                    counts[(use.kind, use.subject)],
                )


def _summarise(
    observations: Iterable[tuple[SeenKind, str, datetime]],
) -> tuple[list[SeenUse], dict[tuple[SeenKind, str], int]]:
    """One use per kind and subject, spanning its first to last occurrence."""
    first: dict[tuple[SeenKind, str], datetime] = {}
    last: dict[tuple[SeenKind, str], datetime] = {}
    counts: dict[tuple[SeenKind, str], int] = defaultdict(int)
    for kind, subject, at in observations:
        key = (kind, subject)
        first[key] = min(first.get(key, at), at)
        last[key] = max(last.get(key, at), at)
        counts[key] += 1
    uses = [
        SeenUse(kind=kind, subject=subject, first_at=first[(kind, subject)], last_at=last[(kind, subject)])
        for kind, subject in first
    ]
    return uses, counts
