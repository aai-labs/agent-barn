import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import batched
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.service import AgentService
from api.domains.anomalies.classification import (
    MAX_ITEMS_PER_DECISION,
    AgentContext,
    classification_request,
    read_classifications,
    severity_level,
)
from api.domains.anomalies.destinations import destination_hosts
from api.domains.anomalies.detection import (
    BASELINE_DAYS,
    RateSignal,
    Sensitivity,
    Verdict,
    error_rate,
    evaluate_cap,
    evaluate_rate,
    has_enough_history,
    rate_baseline,
    rate_threshold,
)
from api.domains.anomalies.models import (
    NEW_SIGNAL_BY_KIND,
    AgentAnomaly,
    AgentAnomalyOverride,
    AgentAnomalyOverrideRead,
    AgentAnomalyOverrideUpdate,
    AgentAnomalyRead,
    AgentNormalBehaviourRead,
    AnomalyDetectionSettingsRead,
    AnomalyClassificationRead,
    AnomalyDetectionSettingsUpdate,
    AnomalySignal,
    ClassificationState,
    RateBaselineRead,
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
from api.domains.decisions.service import DecisionService
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.tool_calls.service import ToolCallService
from api.infrastructure.litellm.decisions import DecisionError
from api.infrastructure.shared.models import PaginatedItems, Pagination

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


def anomaly_read(anomaly: AgentAnomaly) -> AgentAnomalyRead:
    classification = None
    if (
        anomaly.classification_state == ClassificationState.CLASSIFIED.value
        and anomaly.classification_category is not None
        and anomaly.classification_severity is not None
    ):
        probability = (anomaly.classification or {}).get("unusual_probability")
        classification = AnomalyClassificationRead(
            category=anomaly.classification_category,
            severity=severity_level(anomaly.classification_severity),
            unusual_probability=float(probability) if isinstance(probability, int | float) else None,
        )
    return AgentAnomalyRead(
        id=anomaly.id,
        signal=AnomalySignal(anomaly.signal),
        subject=anomaly.subject,
        observed_value=anomaly.observed_value,
        usual_value=anomaly.usual_value,
        threshold=anomaly.threshold,
        started_at=anomaly.started_at,
        last_observed_at=anomaly.last_observed_at,
        ended_at=anomaly.ended_at,
        classification_state=ClassificationState(anomaly.classification_state),
        classification=classification,
    )


# Rows are stamped when inserted but only visible once their transaction commits, so
# the check stops short of "now" to read each row exactly once.
STORAGE_LAG = timedelta(minutes=2)
WINDOW = timedelta(hours=1)
BASELINE = timedelta(days=BASELINE_DAYS)
# A use stored up to this long after the check had read through still counts as new.
# Anything older (a backfill, a replay) is learned instead, since it was not new when
# it happened, or nobody saw it then.
LATE_USE = timedelta(hours=1)
# The cost sync runs every 15 minutes. Past this, it has stopped, and its last figures
# say nothing about what the Agent is doing now.
COST_SYNC_STALE = timedelta(hours=1)
LLM_SIGNALS = (
    AnomalySignal.LLM_CALLS_PER_HOUR,
    AnomalySignal.LLM_TOKENS_PER_HOUR,
    AnomalySignal.LLM_ERROR_RATE,
    AnomalySignal.LLM_CALLS_CAP,
    AnomalySignal.LLM_TOKENS_CAP,
)
# Every argument key `destination_hosts` reads, on either runtime.
DESTINATION_ARGUMENT_KEYS = ("url", "urls", "targetUrl", "action", "command")


@dataclass(frozen=True)
class CheckSummary:
    organizations: int
    agents: int
    failures: int


@dataclass(frozen=True)
class FirstUse:
    signal: AnomalySignal
    subject: str
    at: datetime
    uses: int


@dataclass(frozen=True)
class FirstUseFindings:
    """What a check found new, what it saw, and how far it read."""

    first_uses: list[FirstUse]
    seen: list[SeenUse]
    tool_calls_read_through: datetime
    business_actions_read_through: datetime


RateFinding = tuple[AnomalySignal, Verdict | None, datetime]


@dataclass
class AgentHistory:
    """An Agent's hourly figures over its baseline window and the hour being checked."""

    active_days: int
    tool_calls: list[float]
    error_rates: list[float]
    writes: list[float]
    llm_calls: list[float]
    llm_tokens: list[float]
    llm_error_rates: list[float]
    observed_tool_calls: int
    observed_errors: int
    observed_writes: int
    observed_llm_calls: int | None
    observed_llm_tokens: int | None
    observed_llm_failures: int | None

    @property
    def observed_llm_attempts(self) -> int | None:
        """Every LLM call in the checked hour, failed or not (None before any cost sync)."""
        if self.observed_llm_calls is None or self.observed_llm_failures is None:
            return None
        return self.observed_llm_calls + self.observed_llm_failures


def _error_rates(hours: list[datetime], counts: dict[datetime, tuple[int, int]]) -> list[float]:
    """The error rate of each of `hours` with enough calls to judge, from its (failed,
    all) call counts."""
    return [rate for hour in hours if hour in counts and (rate := error_rate(*counts[hour])) is not None]


def _floor_hour(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


def _baseline_window(until: datetime) -> tuple[datetime, datetime]:
    """The whole hours of the baseline window for a checked hour ending at `until`."""
    return _floor_hour(until - BASELINE), _floor_hour(until - WINDOW)


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
    decision_service: DecisionService

    def windows(self, now: datetime) -> tuple[datetime, datetime | None]:
        """Where the checked hour ends for tool and Business Action figures, and for LLM
        figures, which are complete only up to the last cost sync (None before any)."""
        until = now - STORAGE_LAG
        synced = self.cost_service.last_sync_completed_at()
        return until, min(until, synced) if synced is not None else None

    def run_checks(self, now: datetime | None = None) -> CheckSummary:
        until, cost_until = self.windows(now or datetime.now(UTC))
        organizations = self.repository.enabled_organization_ids()
        agents = failures = 0
        for organization_id in organizations:
            agent_ids = self.agent_service.live_agent_ids(organization_id)
            self.repository.end_ongoing_except(organization_id, agent_ids, until)
            for agent_id in agent_ids:
                agents += 1
                try:
                    self._check_agent(organization_id, agent_id, until, cost_until)
                except Exception:
                    failures += 1
                    logger.exception("Anomaly check failed for agent %s", agent_id)
        return CheckSummary(organizations=len(organizations), agents=agents, failures=failures)

    def check_agent(self, organization_id: UUID, agent_id: UUID, now: datetime) -> None:
        """One check of one Agent, as `run_checks` would make it at `now`."""
        self._check_agent(organization_id, agent_id, *self.windows(now))

    def _check_agent(self, organization_id: UUID, agent_id: UUID, until: datetime, cost_until: datetime | None) -> None:
        """Work out everything first, then record it in one transaction, and only if
        detection has not been turned off (or off and on again) meanwhile. What started
        is classified after the transaction, so a slow provider never holds it open."""
        version = self.repository.detection_version(organization_id)
        if version is None:
            return
        rates, enough, context = self._rate_findings(agent_id, until, cost_until)
        found = self._first_use_findings(agent_id, until, enough)
        started: list[UUID] = []
        with self.repository.check_writes(organization_id, agent_id, version) as writes:
            if writes is None:
                logger.info("Detection changed while agent %s was checked; nothing was recorded", agent_id)
                return
            for signal, verdict, at in rates:
                if verdict is not None and verdict.flagged:
                    if (anomaly_id := writes.open_or_update(signal, verdict, at)) is not None:
                        started.append(anomaly_id)
                else:
                    writes.end_ongoing(signal, at)
            for use in found.first_uses:
                started.append(writes.record_first_use(use.signal, use.subject, use.at, use.uses))
            writes.mark_seen(found.seen)
            writes.save_state(
                tool_calls_read_through=found.tool_calls_read_through,
                business_actions_read_through=found.business_actions_read_through,
            )
        self._classify(agent_id, started, context)

    def _classify(self, agent_id: UUID, anomaly_ids: list[UUID], context: AgentContext) -> None:
        """Ask the decision model about Anomalies that started in this check, once.

        Billed to the Agent. A failure, such as its spend limit, leaves them as the
        statistics flagged them; they are not asked about again, so a spent budget does
        not turn into a billed retry every check. Ongoing ones go along as context.
        """
        if not anomaly_ids:
            return
        anomalies = self.repository.get_anomalies(anomaly_ids)
        other_ongoing = self.repository.ongoing_signals(agent_id, excluding=anomaly_ids)
        for batch in batched(anomalies, MAX_ITEMS_PER_DECISION):
            state, questions = classification_request(batch, context, other_ongoing=other_ongoing)
            try:
                result = self.decision_service.decide(agent_id, state, questions)
            except DecisionError as error:
                logger.warning("Anomaly classification failed for agent %s: %s", agent_id, error.failure.value)
                return
            for anomaly_id, classification in read_classifications(batch, result.answers).items():
                self.repository.set_classification(
                    anomaly_id, classification.category, classification.severity, classification.details
                )

    def _rate_findings(
        self, agent_id: UUID, until: datetime, cost_until: datetime | None
    ) -> tuple[list[RateFinding], bool, AgentContext]:
        """A verdict per rate and cap (None ends what is ongoing), whether the Agent has
        enough history to be judged, and what the decision model is told about it."""
        override = self.settings_repository.get_override(agent_id)
        sensitivity = Sensitivity(override.sensitivity) if override is not None else Sensitivity.NORMAL
        history = self.history(agent_id, until, cost_until)
        enough = has_enough_history(history.active_days)
        findings: list[RateFinding] = []

        def rate(signal: RateSignal, observed: float | None, values: list[float], at: datetime) -> None:
            baseline = rate_baseline(values)
            verdict = None
            if observed is not None and enough and baseline is not None:
                verdict = evaluate_rate(signal, observed, baseline, sensitivity)
            findings.append((AnomalySignal(signal.value), verdict, at))

        rate(RateSignal.TOOL_CALLS_PER_HOUR, history.observed_tool_calls, history.tool_calls, until)
        rate(
            RateSignal.TOOL_ERROR_RATE,
            error_rate(history.observed_errors, history.observed_tool_calls),
            history.error_rates,
            until,
        )
        rate(RateSignal.WRITES_PER_HOUR, history.observed_writes, history.writes, until)
        if cost_until is not None and until - cost_until <= COST_SYNC_STALE:
            rate(RateSignal.LLM_CALLS_PER_HOUR, history.observed_llm_calls, history.llm_calls, cost_until)
            rate(RateSignal.LLM_TOKENS_PER_HOUR, history.observed_llm_tokens, history.llm_tokens, cost_until)
            attempts = history.observed_llm_attempts
            rate(
                RateSignal.LLM_ERROR_RATE,
                error_rate(history.observed_llm_failures or 0, attempts) if attempts is not None else None,
                history.llm_error_rates,
                cost_until,
            )
            findings += _cap_findings(override, history, cost_until)
        elif cost_until is not None:
            # The cost sync has stopped: nothing shows an LLM deviation still going, so
            # it ends where the synced figures do instead of staying open on them.
            findings += [(signal, None, cost_until) for signal in LLM_SIGNALS]
        return findings, enough, AgentContext(sensitivity=sensitivity, active_days=history.active_days)

    def history(self, agent_id: UUID, until: datetime, cost_until: datetime | None) -> AgentHistory:
        """Hourly figures over the baseline window, in whole hours, ending at the start
        of the hour the checked hour begins in, so the two never overlap.

        LLM figures have their own window, ending where the cost sync has got to, so an
        hour with tool calls whose LLM calls are not synced yet does not count as an
        hour without LLM calls.

        Failed LLM calls are kept apart: an hour in which every LLM call failed is not
        an active hour, so a job that keeps failing neither makes the Agent's usual
        rates look idle nor teaches the check that failing is usual.
        """
        tool_since, tool_until = _baseline_window(until)
        llm_window = _baseline_window(cost_until) if cost_until is not None else None
        # Tool activity over both windows: it also marks the hours the LLM window counts.
        activity_since = min(tool_since, llm_window[0]) if llm_window is not None else tool_since
        tools_by_hour = {
            row.hour: row for row in self.tool_call_service.hourly_tool_activity(agent_id, activity_since, tool_until)
        }
        write_hours = {
            row.hour: row.writes for row in self.business_value_service.hourly_writes(agent_id, tool_since, tool_until)
        }
        llm_by_hour = (
            {row.hour: row for row in self.cost_service.hourly_llm_usage(agent_id, *llm_window) if row.calls > 0}
            if llm_window is not None
            else {}
        )
        active = tools_by_hour.keys() | llm_by_hour.keys()
        tool_active = sorted(hour for hour in active if tool_since <= hour < tool_until)
        llm_active = (
            sorted(hour for hour in active if llm_window[0] <= hour < llm_window[1]) if llm_window is not None else []
        )

        observed_tools = self.tool_call_service.hourly_tool_activity(agent_id, until - WINDOW, until)
        observed_writes = self.business_value_service.hourly_writes(agent_id, until - WINDOW, until)
        observed_llm = (
            self.cost_service.hourly_llm_usage(agent_id, cost_until - WINDOW, cost_until)
            if cost_until is not None
            else None
        )
        return AgentHistory(
            active_days=len({hour.date() for hour in [*tool_active, *llm_active]}),
            tool_calls=[float(tools_by_hour[hour].calls) if hour in tools_by_hour else 0.0 for hour in tool_active],
            error_rates=_error_rates(
                tool_active, {hour: (row.errors, row.calls) for hour, row in tools_by_hour.items()}
            ),
            llm_error_rates=_error_rates(
                llm_active, {hour: (row.failures, row.calls + row.failures) for hour, row in llm_by_hour.items()}
            ),
            writes=[float(write_hours.get(hour, 0)) for hour in tool_active],
            llm_calls=[float(llm_by_hour[hour].calls) if hour in llm_by_hour else 0.0 for hour in llm_active],
            llm_tokens=[float(llm_by_hour[hour].tokens) if hour in llm_by_hour else 0.0 for hour in llm_active],
            observed_tool_calls=sum(row.calls for row in observed_tools),
            observed_errors=sum(row.errors for row in observed_tools),
            observed_writes=sum(row.writes for row in observed_writes),
            observed_llm_calls=sum(row.calls for row in observed_llm) if observed_llm is not None else None,
            observed_llm_tokens=sum(row.tokens for row in observed_llm) if observed_llm is not None else None,
            observed_llm_failures=sum(row.failures for row in observed_llm) if observed_llm is not None else None,
        )

    def _first_use_findings(self, agent_id: UUID, until: datetime, enough: bool) -> FirstUseFindings:
        """What the Agent used for the first time in its baseline window.

        An Agent read for the first time (no state) only learns what it already uses,
        from its baseline window, and flags nothing: everything would look new.
        """
        state = self.repository.get_state(agent_id)
        learning = state is None
        tool_calls_after = None if state is None else state.tool_calls_read_through
        actions_after = None if state is None else state.business_actions_read_through
        # Older activity counts as unseen anyway, and bounding by it keeps the read on
        # the Agent's recent rows.
        occurred_since = until - BASELINE
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
        recent: list[tuple[SeenKind, str, datetime]] = []
        old: list[tuple[SeenKind, str, datetime]] = []

        def observe(kind: SeenKind, subject: str, at: datetime, read_after: datetime | None) -> None:
            is_recent = read_after is not None and at >= read_after - LATE_USE
            (recent if is_recent else old).append((kind, subject, at))

        for call in calls:
            observe(SeenKind.TOOL, call.tool_name, call.occurred_at, tool_calls_after)
            for host in sorted(destination_hosts(call.tool_name, call.arguments)):
                observe(SeenKind.DESTINATION, host, call.occurred_at, tool_calls_after)
        for action in actions:
            observe(SeenKind.INTEGRATION, action.integration, action.occurred_at, actions_after)
            observe(
                SeenKind.INTEGRATION_ACTION, f"{action.integration} {action.verb}", action.occurred_at, actions_after
            )
        recent_uses, counts = _summarise(recent)
        old_uses, _ = _summarise(old)
        # A subject can be both recent and old (a backfill alongside a new use); the
        # ledger takes it once, spanning both.
        seen, _ = _summarise([*recent, *old])
        return FirstUseFindings(
            first_uses=self._first_uses(agent_id, recent_uses, counts, also_seen=old_uses)
            if not learning and enough
            else [],
            seen=seen,
            tool_calls_read_through=max(until, tool_calls_after or until),
            business_actions_read_through=max(until, actions_after or until),
        )

    def _first_uses(
        self,
        agent_id: UUID,
        uses: list[SeenUse],
        counts: dict[tuple[SeenKind, str], int],
        *,
        also_seen: list[SeenUse],
    ) -> list[FirstUse]:
        """The `uses` not seen in the baseline window before them, counting the ledger
        and `also_seen` (older uses read in the same check, not yet recorded)."""
        by_kind: dict[SeenKind, list[SeenUse]] = defaultdict(list)
        for use in uses:
            by_kind[use.kind].append(use)
        older: dict[tuple[SeenKind, str], datetime] = {(use.kind, use.subject): use.last_at for use in also_seen}
        new_integrations: set[str] = set()
        first_uses: list[FirstUse] = []
        for kind in (SeenKind.TOOL, SeenKind.DESTINATION, SeenKind.INTEGRATION, SeenKind.INTEGRATION_ACTION):
            kind_uses = by_kind.get(kind, [])
            last_seen = self.repository.last_seen(agent_id, kind, [use.subject for use in kind_uses])
            for use in kind_uses:
                seen_at = max(
                    (at for at in (last_seen.get(use.subject), older.get((kind, use.subject))) if at is not None),
                    default=None,
                )
                if seen_at is not None and seen_at >= use.first_at - BASELINE:
                    continue
                if kind is SeenKind.INTEGRATION:
                    new_integrations.add(use.subject)
                # A brand-new integration is one Anomaly, not one more per action on it.
                if kind is SeenKind.INTEGRATION_ACTION and use.subject.split(" ", 1)[0] in new_integrations:
                    continue
                first_uses.append(
                    FirstUse(NEW_SIGNAL_BY_KIND[kind], use.subject, use.first_at, counts[(use.kind, use.subject)])
                )
        return first_uses


def _cap_findings(override: AgentAnomalyOverride | None, history: AgentHistory, at: datetime) -> list[RateFinding]:
    caps = (
        (
            AnomalySignal.LLM_TOKENS_CAP,
            override.max_llm_tokens_per_hour if override else None,
            history.observed_llm_tokens,
        ),
        (
            AnomalySignal.LLM_CALLS_CAP,
            override.max_llm_calls_per_hour if override else None,
            # Failed calls still reach the provider, so the cap counts them.
            history.observed_llm_attempts,
        ),
    )
    return [
        (signal, evaluate_cap(observed, cap) if cap is not None and observed is not None else None, at)
        for signal, cap, observed in caps
    ]


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
    anomaly_repository: AnomalyRepository
    check_service: AnomalyCheckService
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

    def list_anomalies(
        self, agent_id: UUID, context: CurrentUserContext, pagination: Pagination
    ) -> PaginatedItems[AgentAnomalyRead]:
        agent = self._require_agent(agent_id, context, PermissionKey.ANOMALY_READ, READ_DENIED_DETAIL)
        items, total = self.anomaly_repository.list_anomalies(agent.id, pagination)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[anomaly_read(item) for item in items],
        )

    def normal_behaviour(self, agent_id: UUID, context: CurrentUserContext) -> AgentNormalBehaviourRead:
        """What the check currently counts as normal for the Agent, worked out now
        exactly as the next check would."""
        agent = self._require_agent(agent_id, context, PermissionKey.ANOMALY_READ, READ_DENIED_DETAIL)
        now = datetime.now(UTC)
        until, cost_until = self.check_service.windows(now)
        history = self.check_service.history(agent.id, until, cost_until)
        override = self.settings_repository.get_override(agent.id)
        override_values = override_read(override)
        rated = [
            (RateSignal.TOOL_CALLS_PER_HOUR, history.tool_calls),
            (RateSignal.TOOL_ERROR_RATE, history.error_rates),
            (RateSignal.WRITES_PER_HOUR, history.writes),
        ]
        if cost_until is not None:
            rated += [
                (RateSignal.LLM_CALLS_PER_HOUR, history.llm_calls),
                (RateSignal.LLM_TOKENS_PER_HOUR, history.llm_tokens),
                (RateSignal.LLM_ERROR_RATE, history.llm_error_rates),
            ]
        rates = [
            RateBaselineRead(
                signal=signal,
                usual=baseline.median,
                threshold=rate_threshold(signal, baseline, override_values.sensitivity),
                active_hours=baseline.active_hours,
            )
            for signal, values in rated
            if (baseline := rate_baseline(values)) is not None
        ]
        seen: dict[SeenKind, list[str]] = defaultdict(list)
        for row in self.anomaly_repository.seen_since(agent.id, now - BASELINE):
            seen[SeenKind(row.kind)].append(row.subject)
        settings = self.settings_repository.get_settings(agent.organization_id)
        return AgentNormalBehaviourRead(
            detection_enabled=settings is not None and settings.enabled,
            enough_history=has_enough_history(history.active_days),
            active_days=history.active_days,
            rates=rates,
            tools=sorted(seen[SeenKind.TOOL]),
            integrations=sorted(seen[SeenKind.INTEGRATION]),
            integration_actions=sorted(seen[SeenKind.INTEGRATION_ACTION]),
            destinations=sorted(seen[SeenKind.DESTINATION]),
            override=override_values,
            can_manage=self.permission_policy.resolve(context, agent.organization_id, PermissionKey.ANOMALY_MANAGE)
            is not None,
        )

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
