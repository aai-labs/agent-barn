import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.models import Agent, AgentStatus, PlatformAgentIdentity
from api.domains.agents.provisioning_errors import persisted_provisioning_error
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.resource_limits.models import ResourceLimitsRead
from api.domains.resource_limits.service import ResourceLimitsService
from api.domains.resource_usage.models import (
    PlatformAgentDetailsRead,
    PlatformAgentResourceUsageRead,
    PlatformAgentUsagePoint,
    PlatformAgentUsageRead,
    PlatformCapacityRead,
    PlatformOrganizationUsageRead,
    PlatformResourceUsageRead,
    PlatformUsagePoint,
    PlatformUsageTotalsRead,
    ResourceUsageAvailability,
    ResourceUsageRange,
    ResourceUsageState,
    UsageWindow,
    resolve_usage_window,
)
from api.domains.resource_usage.repository import ResourceUsageRepository
from api.domains.resource_usage.service import ResourceUsageService, usage_state
from api.infrastructure.prometheus.client import PrometheusError

logger = logging.getLogger(__name__)

# The same "now" as the Organization overview: limits looked up over the last few
# minutes, throttling judged over the last hour.
_LIMIT_WINDOW_SECONDS = 300
_THROTTLE_WINDOW_SECONDS = 3600

_HAS_CONTAINER = {AgentStatus.RUNNING, AgentStatus.ERROR}


@dataclass
class _Sums:
    """Running totals for one Organization, or for containers with no live Agent."""

    name: str | None
    agents_with_container: int = 0
    agents_reporting: int = 0
    memory_working_set_bytes: float = 0.0
    memory_limit_bytes: float = 0.0
    cpu_cores: float = 0.0
    cpu_limit_cores: float = 0.0

    def add(self, fields: Mapping[str, float]) -> None:
        self.agents_reporting += 1
        self.memory_working_set_bytes += fields.get("memory_working_set_bytes", 0.0)
        self.memory_limit_bytes += fields.get("memory_limit_bytes", 0.0)
        self.cpu_cores += fields.get("cpu_cores", 0.0)
        self.cpu_limit_cores += fields.get("cpu_limit_cores", 0.0)

    def merge(self, other: _Sums) -> None:
        self.agents_with_container += other.agents_with_container
        self.agents_reporting += other.agents_reporting
        self.memory_working_set_bytes += other.memory_working_set_bytes
        self.memory_limit_bytes += other.memory_limit_bytes
        self.cpu_cores += other.cpu_cores
        self.cpu_limit_cores += other.cpu_limit_cores

    def totals(self) -> PlatformUsageTotalsRead:
        return PlatformUsageTotalsRead(
            agents_with_container=self.agents_with_container,
            agents_reporting=self.agents_reporting,
            memory_working_set_bytes=int(self.memory_working_set_bytes),
            memory_limit_bytes=int(self.memory_limit_bytes),
            cpu_cores=self.cpu_cores,
            cpu_limit_cores=self.cpu_limit_cores,
        )


@dataclass(frozen=True)
class PlatformUsage:
    totals: PlatformUsageTotalsRead
    organizations: list[PlatformOrganizationUsageRead]
    agents: list[PlatformAgentUsageRead]


def count_with_container(identities: Sequence[PlatformAgentIdentity], organization_id: UUID | None) -> int:
    return sum(
        1 for agent in identities if agent.status in _HAS_CONTAINER and organization_id in (None, agent.organization_id)
    )


def build_platform_usage(
    identities: Sequence[PlatformAgentIdentity],
    fields: Mapping[UUID, Mapping[str, float]],
    organization_id: UUID | None = None,
) -> PlatformUsage:
    """Totals, per-Organization sums and per-Agent rows from the current readings.

    Every reading is placed by its Agent's Organization in the database, never by a
    label. A reading with no live Agent behind it goes to its own bucket (key None), so
    the Organization rows still add up to the platform total. A stopped Agent can still
    show a reading for a few minutes after it stops; it is left out, as on the
    Organization overview, since it no longer has a container.
    """
    by_id = {agent.id: agent for agent in identities}
    sums: dict[UUID | None, _Sums] = {}
    for agent in identities:
        if agent.status in _HAS_CONTAINER:
            sums.setdefault(agent.organization_id, _Sums(agent.organization_name)).agents_with_container += 1

    agents: list[PlatformAgentUsageRead] = []
    for agent_id, readings in fields.items():
        if usage_state(readings, has_series=False) != ResourceUsageState.REPORTING:
            continue
        identity = by_id.get(agent_id)
        if identity is not None and identity.status not in _HAS_CONTAINER:
            continue
        key = identity.organization_id if identity else None
        bucket = sums.setdefault(key, _Sums(identity.organization_name if identity else None))
        bucket.add(readings)
        if organization_id is not None and key != organization_id:
            continue
        agents.append(
            PlatformAgentUsageRead(
                agent_id=agent_id,
                agent_name=identity.name if identity else None,
                organization_id=key,
                organization_name=identity.organization_name if identity else None,
                memory_working_set_bytes=_whole(readings.get("memory_working_set_bytes")),
                memory_limit_bytes=_whole(readings.get("memory_limit_bytes")),
                cpu_cores=readings.get("cpu_cores"),
                cpu_limit_cores=readings.get("cpu_limit_cores"),
                cpu_throttled_ratio=readings.get("cpu_throttled_ratio"),
            )
        )

    organizations = [
        PlatformOrganizationUsageRead(
            organization_id=key, organization_name=bucket.name, **bucket.totals().model_dump()
        )
        for key, bucket in sums.items()
    ]
    # Heaviest first, and the bucket with no Organization last whatever it holds.
    organizations.sort(key=lambda row: (row.organization_id is None, -(row.memory_working_set_bytes or 0)))
    agents.sort(key=lambda row: -(row.memory_working_set_bytes or 0))

    if organization_id is None:
        everything = _Sums(None)
        for bucket in sums.values():
            everything.merge(bucket)
        totals = everything.totals()
    else:
        totals = sums.get(organization_id, _Sums(None)).totals()

    return PlatformUsage(totals=totals, organizations=organizations, agents=agents)


def _error_summary(agent: Agent) -> str | None:
    """The fixed-copy summary of an Agent's provisioning failure, never its detail.

    Rebuilt from the stored category code, so a legacy message that came straight from the
    cluster is dropped rather than shown.
    """
    if agent.status != AgentStatus.ERROR:
        return None
    stored = persisted_provisioning_error(
        code=agent.last_error_code, detail=agent.last_error_detail, legacy_message=agent.last_error
    )
    return stored.summary if stored else None


def _whole(value: float | None) -> int | None:
    return None if value is None else int(value)


def _capacity(limits: ResourceLimitsRead, committed: Mapping[str, float] | None) -> PlatformCapacityRead:
    """The ceilings an administrator entered, beside what the namespace commits.

    `committed` is None when the source could not be read; a resource it did not answer
    for is also left None, so "unknown" is never drawn as "nothing committed".
    """
    committed = committed or {}
    return PlatformCapacityRead(
        memory_limit_bytes=limits.memory_limit_bytes,
        cpu_limit_cores=limits.cpu_limit_cores,
        limits_updated_at=limits.updated_at,
        memory_committed_bytes=_whole(committed.get("memory")),
        cpu_committed_cores=committed.get("cpu"),
    )


@inject
@singleton
@dataclass
class PlatformResourceUsageService:
    """CPU and memory of every Agent's container, across all Organizations.

    A separate service and read model from the Organization overview, per the Platform
    oversight ADR, and recorded as Platform Oversight Data in
    `docs/adr/2026-10-01-resource-usage-as-platform-oversight-data.md`. Authorization is
    the route's `require_platform_admin`; nothing here re-scopes by membership, because a
    Platform Administrator deliberately has none. Agents and Organizations are named
    from the database, never from Prometheus labels.
    """

    agent_repository: AgentRepository
    usage_repository: ResourceUsageRepository
    # Composed as services, never through their repositories, as the stats service does.
    resource_limits_service: ResourceLimitsService
    agent_service: AgentService
    resource_usage_service: ResourceUsageService
    organization_lookup: OrganizationLookupService
    agent_settings_lookup: AgentSettingsLookupService

    def get_usage(self, usage_range: ResourceUsageRange, organization_id: UUID | None) -> PlatformResourceUsageRead:
        now = datetime.now(UTC)
        window = resolve_usage_window(usage_range, now)
        identities = self.agent_repository.find_live_for_platform_usage()
        limits = self.resource_limits_service.get_limits()

        def unmeasured(availability: ResourceUsageAvailability) -> PlatformResourceUsageRead:
            return PlatformResourceUsageRead(
                range=usage_range,
                from_date=window.start,
                to_date=window.end,
                step_seconds=window.step_seconds,
                observed_at=now,
                availability=availability,
                organization_id=organization_id,
                totals=PlatformUsageTotalsRead(agents_with_container=count_with_container(identities, organization_id)),
                # The limits are in the database, so they are there when the source is not.
                capacity=_capacity(limits, None),
            )

        if not self.usage_repository.is_configured:
            return unmeasured(ResourceUsageAvailability.NOT_CONFIGURED)

        try:
            fields = self.usage_repository.all_current_fields(
                at=now,
                window_seconds=_LIMIT_WINDOW_SECONDS,
                throttle_window_seconds=_THROTTLE_WINDOW_SECONDS,
            )
            series = self._combined_series(window, identities, organization_id)
            committed = self.usage_repository.committed_limits(at=now)
        except PrometheusError:
            logger.warning("Platform resource usage is unavailable", exc_info=True)
            return unmeasured(ResourceUsageAvailability.UNAVAILABLE)

        usage = build_platform_usage(identities, fields, organization_id)
        memory = series.get("memory_working_set_bytes", {})
        cpu = series.get("cpu_cores", {})
        return PlatformResourceUsageRead(
            range=usage_range,
            from_date=window.start,
            to_date=window.end,
            step_seconds=window.step_seconds,
            observed_at=now,
            availability=ResourceUsageAvailability.AVAILABLE,
            organization_id=organization_id,
            totals=usage.totals,
            capacity=_capacity(limits, committed),
            organizations=usage.organizations,
            agents=usage.agents,
            series=[
                PlatformUsagePoint(
                    bucket=bucket,
                    memory_working_set_bytes=_whole(memory.get(int(bucket.timestamp()))),
                    cpu_cores=cpu.get(int(bucket.timestamp())),
                )
                for bucket in window.timeline()
            ],
        )

    def get_agent_details(self, agent_id: UUID) -> PlatformAgentDetailsRead:
        """Status and usage for one live Agent, for a Heaviest agents row that is opened.

        The same facts the Organization overview's panels show, from the same sources, but
        through the Platform's own read model: no log text, no free-text health reason and
        no failure detail leave here. Authorization is the route's `require_platform_admin`.
        """
        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

        has_container = agent.status != AgentStatus.STOPPED
        health = self.agent_service.agent_health(agent) if has_container else None
        diagnostics = self.agent_service.runtime_restarts(agent) if has_container else None
        usage = self.resource_usage_service.usage_for(agent, ResourceUsageRange.ONE_DAY) if has_container else None
        organization_id = agent.organization_id
        return PlatformAgentDetailsRead(
            agent_id=agent.id,
            name=agent.name,
            status=agent.status,
            agent_type=agent.agent_type,
            effective_model=agent.model or self.agent_settings_lookup.resolve_default_model(organization_id),
            created_at=agent.created_at,
            organization_id=organization_id,
            organization_name=self.organization_lookup.get_name(organization_id),
            last_error_summary=_error_summary(agent),
            health_status=health.status if health else None,
            restart_count=diagnostics.restart_count if diagnostics and diagnostics.available else None,
            termination_reason=diagnostics.termination_reason if diagnostics and diagnostics.available else None,
            resource_usage=(
                PlatformAgentResourceUsageRead(
                    **usage.model_dump(exclude={"agent_id", "series"}),
                    series=[PlatformAgentUsagePoint(**point.model_dump()) for point in usage.series],
                )
                if usage
                else None
            ),
        )

    def _combined_series(
        self,
        window: UsageWindow,
        identities: Sequence[PlatformAgentIdentity],
        organization_id: UUID | None,
    ) -> dict[str, dict[int, float]]:
        """The whole platform, or one Organization's live Agents.

        Narrowed by the Agents the database places in the Organization rather than by
        the `org_id` label, so the chart counts the Agents the totals count. A deleted
        Agent's history is therefore left out of an Organization's chart, though it is
        in the platform's.
        """
        if organization_id is None:
            return self.usage_repository.combined_series(window)
        agent_ids = [agent.id for agent in identities if agent.organization_id == organization_id]
        if not agent_ids:
            return {}
        return self.usage_repository.combined_series(window, (organization_id, agent_ids))
