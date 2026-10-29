import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from injector import inject, singleton

from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentFilter, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.costs.service import CostService
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.catalog import PermissionKey
from api.domains.resource_usage.models import (
    OVERVIEW_MAX_AGENTS,
    AgentOverviewItemRead,
    AgentOverviewRead,
    AgentOverviewSpendRead,
    AgentResourceUsageRead,
    AgentUsageSnapshotRead,
    ResourceUsageAvailability,
    ResourceUsagePoint,
    ResourceUsageRange,
    ResourceUsageState,
    resolve_usage_window,
)
from api.domains.resource_usage.repository import ResourceUsageRepository
from api.infrastructure.prometheus.client import PrometheusError

logger = logging.getLogger(__name__)

# The overview shows what an Agent is doing now: a limit is looked up over the last
# few minutes, and throttling is judged over the last hour.
_OVERVIEW_LIMIT_WINDOW_SECONDS = 300
_OVERVIEW_THROTTLE_WINDOW_SECONDS = 3600


def usage_state(fields: Mapping[str, float], has_series: bool) -> ResourceUsageState:
    """What the source knows about one Agent, from its current fields and its history."""
    if has_series or "memory_working_set_bytes" in fields or "cpu_cores" in fields:
        return ResourceUsageState.REPORTING
    available = fields.get("cgroup_metrics_available")
    if available == 0:
        return ResourceUsageState.UNSUPPORTED
    # Scraped but never reported the availability gauge: the healthz script predates it,
    # and the Agent starts reporting once it is restarted.
    if fields.get("up") == 1 and available is None:
        return ResourceUsageState.RESTART_REQUIRED
    return ResourceUsageState.NO_DATA


def _whole(value: float | None) -> int | None:
    return None if value is None else int(value)


def build_snapshot(fields: Mapping[str, float], has_series: bool = False) -> AgentUsageSnapshotRead:
    return AgentUsageSnapshotRead(
        state=usage_state(fields, has_series),
        memory_working_set_bytes=_whole(fields.get("memory_working_set_bytes")),
        memory_limit_bytes=_whole(fields.get("memory_limit_bytes")),
        memory_request_bytes=_whole(fields.get("memory_request_bytes")),
        cpu_cores=fields.get("cpu_cores"),
        cpu_limit_cores=fields.get("cpu_limit_cores"),
        cpu_request_cores=fields.get("cpu_request_cores"),
        cpu_throttled_ratio=fields.get("cpu_throttled_ratio"),
    )


def agent_requests(
    repository: ResourceUsageRepository, agent_ids: list[UUID], now: datetime
) -> dict[UUID, dict[str, float]]:
    """What these Agents' pods request, or nothing when the cluster's figures cannot be read.

    `agent_ids` are Agents the caller has already been allowed to measure, and only they are
    asked about. Everything else on the page stands without the requests, so a failure here
    leaves them unknown instead of failing the answer.
    """
    try:
        return repository.agent_requests(at=now, agent_ids=agent_ids)
    except PrometheusError:
        logger.warning("Agent requests are unavailable", exc_info=True)
        return {}


@inject
@singleton
@dataclass
class ResourceUsageService:
    """One Agent's CPU and memory, now and over a window.

    Gated by `activity.read`, the same as runtime diagnostics and health: it says how the
    Agent's container is doing, which is the same kind of fact. A source that cannot be
    reached is an answer (`availability`), not an error, so the tab can explain itself.
    """

    repository: ResourceUsageRepository
    agent_authorization: AgentAuthorization

    def get_agent_resource_usage(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        usage_range: ResourceUsageRange,
    ) -> AgentResourceUsageRead:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        return self.usage_for(agent, usage_range)

    def usage_for(self, agent: Agent, usage_range: ResourceUsageRange) -> AgentResourceUsageRead:
        """One Agent's usage over a range, for an Agent already authorized by the caller.

        The Organization route requires `activity.read` first, and the Platform view sits
        behind `require_platform_admin`. A source that cannot be reached is an answer
        (`availability`), not an error.
        """
        now = datetime.now(UTC)
        window = resolve_usage_window(usage_range, now)

        def respond(availability: ResourceUsageAvailability, **fields: Any) -> AgentResourceUsageRead:
            return AgentResourceUsageRead(
                agent_id=agent.id,
                range=usage_range,
                from_date=window.start,
                to_date=window.end,
                step_seconds=window.step_seconds,
                observed_at=now,
                availability=availability,
                **fields,
            )

        if not self.repository.is_configured:
            return respond(ResourceUsageAvailability.NOT_CONFIGURED)

        try:
            current = self.repository.current_fields(
                agent.organization_id,
                [agent.id],
                at=now,
                window_seconds=usage_range.seconds,
                throttle_window_seconds=usage_range.seconds,
            ).get(agent.id, {})
            series = self.repository.series_fields(agent.organization_id, agent.id, window)
        except PrometheusError:
            logger.warning("Resource usage is unavailable for agent %s", agent.id, exc_info=True)
            return respond(ResourceUsageAvailability.UNAVAILABLE)
        current = {**current, **agent_requests(self.repository, [agent.id], now).get(agent.id, {})}

        memory = series.get("memory_working_set_bytes", {})
        cpu = series.get("cpu_cores", {})
        throttled = series.get("cpu_throttled_ratio", {})
        points = []
        for bucket in window.timeline():
            second = int(bucket.timestamp())
            points.append(
                ResourceUsagePoint(
                    bucket=bucket,
                    memory_working_set_bytes=_whole(memory.get(second)),
                    cpu_cores=cpu.get(second),
                    cpu_throttled_ratio=throttled.get(second),
                )
            )

        snapshot = build_snapshot(current, has_series=bool(memory or cpu))
        return respond(
            ResourceUsageAvailability.AVAILABLE,
            state=snapshot.state,
            memory_working_set_bytes=snapshot.memory_working_set_bytes,
            memory_limit_bytes=snapshot.memory_limit_bytes,
            memory_request_bytes=snapshot.memory_request_bytes,
            memory_peak_bytes=_whole(max(memory.values(), default=None)),
            cpu_cores=snapshot.cpu_cores,
            cpu_limit_cores=snapshot.cpu_limit_cores,
            cpu_request_cores=snapshot.cpu_request_cores,
            cpu_average_cores=(sum(cpu.values()) / len(cpu)) if cpu else None,
            cpu_throttled_ratio=snapshot.cpu_throttled_ratio,
            series=points,
        )


@inject
@singleton
@dataclass
class AgentOverviewService:
    """Every Agent the caller can read, with status, spend and resource usage.

    Each figure is gated per Agent by the permission that already guards it: spend by
    `cost.read`, resource usage by `activity.read`. A row the caller may see but not
    measure shows that figure as null, so no one is handed a number they could not open.
    There is deliberately no Organization total: that stays behind Organization-level
    `cost.read`.
    """

    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
    agent_settings_lookup: AgentSettingsLookupService
    cost_service: CostService
    usage_repository: ResourceUsageRepository

    def get_overview(self, context: CurrentUserContext, window: StatsWindow) -> AgentOverviewRead:
        read_scope = self.agent_authorization.require_collection_scope(context, PermissionKey.AGENT_READ)
        organization_id = read_scope.organization_id
        # Every Agent the caller can read, not a page of them: the cap below must drop the
        # Agents that spent least, and a page in creation order would drop the newest
        # instead, which can be the biggest spenders in a page that opens sorted by spend.
        everyone, total = self.agent_repository.find_all_active(read_scope, AgentFilter(), None)
        allowed = self.agent_authorization.allowed_actions(context, everyone)

        spend = self.cost_service.spend_for_agents(
            context, window, [a.id for a in everyone if PermissionKey.COST_READ in allowed.get(a.id, [])]
        )
        # Highest spend first, oldest first among equals. An Agent whose spend the caller may
        # not read ranks with those that spent nothing, since no figure can place it higher.
        agents = sorted(everyone, key=lambda a: (-(spend[a.id].spend if a.id in spend else 0), a.created_at))[
            :OVERVIEW_MAX_AGENTS
        ]
        # A stopped Agent has no container to measure, so it is not asked about.
        measurable = [
            a.id
            for a in agents
            if PermissionKey.ACTIVITY_READ in allowed.get(a.id, []) and a.status != AgentStatus.STOPPED
        ]
        availability, snapshots = self._snapshots(organization_id, measurable)
        default_model = self.agent_settings_lookup.resolve_default_model(organization_id)

        items = []
        for agent in agents:
            actions = allowed.get(agent.id, [])
            totals = spend.get(agent.id)
            items.append(
                AgentOverviewItemRead(
                    id=agent.id,
                    name=agent.name,
                    status=agent.status,
                    agent_type=agent.agent_type,
                    effective_model=agent.model or default_model,
                    created_at=agent.created_at,
                    allowed_actions=actions,
                    spend=(
                        AgentOverviewSpendRead(
                            spend=float(totals.spend) if totals else 0.0,
                            calls=totals.calls if totals else 0,
                            last_call_at=totals.last_call_at if totals else None,
                        )
                        if PermissionKey.COST_READ in actions
                        else None
                    ),
                    resource_usage=snapshots.get(agent.id),
                )
            )
        return AgentOverviewRead(
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            resource_usage_availability=availability,
            total=total,
            items=items,
        )

    def _snapshots(
        self, organization_id: UUID, agent_ids: list[UUID]
    ) -> tuple[ResourceUsageAvailability, dict[UUID, AgentUsageSnapshotRead]]:
        if not self.usage_repository.is_configured:
            return ResourceUsageAvailability.NOT_CONFIGURED, {}
        if not agent_ids:
            return ResourceUsageAvailability.AVAILABLE, {}
        try:
            fields = self.usage_repository.current_fields(
                organization_id,
                agent_ids,
                at=datetime.now(UTC),
                window_seconds=_OVERVIEW_LIMIT_WINDOW_SECONDS,
                throttle_window_seconds=_OVERVIEW_THROTTLE_WINDOW_SECONDS,
            )
        except PrometheusError:
            # Spend and status still render; only the usage columns go blank.
            logger.warning("Resource usage is unavailable for the agents overview", exc_info=True)
            return ResourceUsageAvailability.UNAVAILABLE, {}
        requests = agent_requests(self.usage_repository, agent_ids, datetime.now(UTC))
        return ResourceUsageAvailability.AVAILABLE, {
            agent_id: build_snapshot({**fields.get(agent_id, {}), **requests.get(agent_id, {})})
            for agent_id in agent_ids
        }
