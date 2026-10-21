import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from injector import inject, singleton
from kubernetes.client import V1PersistentVolumeClaim, V1Pod, V1ResourceQuota
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from api.domains.agents.repository import AgentRepository
from api.domains.environment_health import cluster
from api.domains.environment_health.models import (
    CapacityLevel,
    CapacityLineRead,
    CoreServiceRead,
    EnvironmentHealthRead,
    EnvironmentSource,
    EnvironmentSourceRead,
    FailedAgentRead,
    FiringAlertRead,
    HealthLevel,
    SourceState,
    UnhealthyRuntimeRead,
    WorkloadsRead,
)
from api.domains.environment_health.repository import EnvironmentHealthRepository
from api.domains.resource_limits.models import ResourceLimitsRead
from api.domains.resource_limits.service import ResourceLimitsService
from api.domains.resource_usage.platform_service import PlatformResourceUsageService
from api.infrastructure.prometheus.client import PrometheusError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _state_of(error: Exception) -> SourceState:
    if isinstance(error, ApiException) and error.status == 403:
        return SourceState.FORBIDDEN
    if isinstance(error, ConfigException):
        return SourceState.NOT_CONFIGURED
    return SourceState.UNAVAILABLE


def overall_level(
    *,
    sources: dict[EnvironmentSource, SourceState],
    services: Sequence[CoreServiceRead],
    capacity: Sequence[CapacityLineRead],
    workloads: WorkloadsRead,
    unhealthy_runtimes: Sequence[UnhealthyRuntimeRead],
    failed_agents: Sequence[FailedAgentRead],
    alerts: Sequence[FiringAlertRead],
) -> HealthLevel:
    """The worst of what the page shows.

    Critical when a platform service has no ready replica, a quota line is at or past 90%,
    or a critical alert is firing. A warning for anything else that needs a look. Unknown when
    neither pods nor Deployments could be read, since nothing else says whether the platform runs.
    """
    if (
        sources.get(EnvironmentSource.PODS) != SourceState.AVAILABLE
        and sources.get(EnvironmentSource.DEPLOYMENTS) != SourceState.AVAILABLE
    ):
        return HealthLevel.UNKNOWN
    if (
        any(service.level == HealthLevel.CRITICAL for service in services)
        or any(line.level == CapacityLevel.CRITICAL for line in capacity)
        or any(alert.severity == "critical" for alert in alerts)
    ):
        return HealthLevel.CRITICAL
    if (
        any(service.level == HealthLevel.WARNING for service in services)
        or any(line.level in {CapacityLevel.WARNING, CapacityLevel.CEILING_OUT_OF_DATE} for line in capacity)
        or workloads.issues
        or unhealthy_runtimes
        or failed_agents
        or alerts
    ):
        return HealthLevel.WARNING
    return HealthLevel.OK


@inject
@singleton
@dataclass
class EnvironmentHealthService:
    """The health and capacity of the namespace the platform runs in, for Platform Administrators.

    Read-only, and Platform Oversight Data under
    `docs/adr/2026-10-20-environment-health-as-platform-oversight-data.md`. Authorization is
    the route's `require_platform_admin`; nothing here re-scopes by membership, because a
    Platform Administrator deliberately has none.

    Each source is read on its own. One that is refused or cannot answer leaves its part of
    the page empty and says so in `sources`; the rest of the page still renders. Agents and
    Organizations are named from the database, never from a label.
    """

    repository: EnvironmentHealthRepository
    agent_repository: AgentRepository
    # Composed as services, never through their repositories, as the stats service does.
    resource_limits_service: ResourceLimitsService
    platform_usage_service: PlatformResourceUsageService

    def get_health(self) -> EnvironmentHealthRead:
        now = datetime.now(UTC)
        sources: dict[EnvironmentSource, SourceState] = {}
        identities = cluster.identities_by_id(self.agent_repository.find_live_for_platform_usage())

        def read(source: EnvironmentSource, fetch: Callable[[], T]) -> T | None:
            try:
                value = fetch()
            except Exception as error:
                state = _state_of(error)
                if state == SourceState.UNAVAILABLE:
                    logger.warning("Environment health source %s is unavailable", source.value, exc_info=True)
                sources[source] = state
                return None
            sources[source] = SourceState.AVAILABLE
            return value

        pods = read(EnvironmentSource.PODS, self.repository.pods)
        deployments = read(EnvironmentSource.DEPLOYMENTS, self.repository.deployments)
        stateful_sets = read(EnvironmentSource.STATEFUL_SETS, self.repository.stateful_sets)
        claims = read(EnvironmentSource.VOLUME_CLAIMS, self.repository.volume_claims)
        quotas = read(EnvironmentSource.RESOURCE_QUOTAS, self.repository.resource_quotas)
        events = read(EnvironmentSource.EVENTS, self.repository.warning_events)

        alert_samples = runtime_samples = None
        if not self.repository.prometheus_configured:
            sources[EnvironmentSource.PROMETHEUS] = SourceState.NOT_CONFIGURED
        else:
            try:
                alert_samples = self.repository.firing_alerts(at=now)
                runtime_samples = self.repository.runtime_health(at=now)
                sources[EnvironmentSource.PROMETHEUS] = SourceState.AVAILABLE
            except PrometheusError:
                logger.warning("Environment health cannot read Prometheus", exc_info=True)
                sources[EnvironmentSource.PROMETHEUS] = SourceState.UNAVAILABLE
                alert_samples = runtime_samples = None

        services = cluster.core_services(deployments or [], stateful_sets or [])
        workloads = cluster.workloads(pods, identities, now) if pods is not None else WorkloadsRead()
        alerts = cluster.firing_alerts(alert_samples or [], identities)
        unhealthy = cluster.unhealthy_runtimes(
            runtime_samples or [], identities, cluster.agent_pod_readiness(pods or [])
        )
        failed = cluster.failed_agents(self.agent_repository.find_failed_for_platform())
        ceilings = self.resource_limits_service.get_limits()
        capacity = self._capacity(now, ceilings, quotas, claims, pods)

        return EnvironmentHealthRead(
            observed_at=now,
            namespace=self.repository.namespace,
            level=overall_level(
                sources=sources,
                services=services,
                capacity=capacity,
                workloads=workloads,
                unhealthy_runtimes=unhealthy,
                failed_agents=failed,
                alerts=alerts,
            ),
            sources=[EnvironmentSourceRead(source=source, state=state) for source, state in sources.items()],
            ceilings=ceilings,
            services=services,
            alerts=alerts,
            capacity=capacity,
            volumes=cluster.volume_allocation(claims or [], identities),
            workloads=workloads,
            unhealthy_runtimes=unhealthy,
            failed_agents=failed,
            events=cluster.warning_events(events or [], identities, now),
        )

    def _capacity(
        self,
        now: datetime,
        ceilings: ResourceLimitsRead,
        quotas: list[V1ResourceQuota] | None,
        claims: list[V1PersistentVolumeClaim] | None,
        pods: list[V1Pod] | None,
    ) -> list[CapacityLineRead]:
        """The namespace's quota when it can be read, otherwise the ceilings entered by hand.

        The tenant account has no `resourcequotas` rule today, so the entered ceilings are the
        usual answer (see `docs/adr/2026-10-01-capacity-limits-entered-by-hand.md`). Once the
        cluster's owners grant the read, the quota's own figures take over with no change here.
        """
        if quotas:
            return cluster.quota_lines(quotas)
        return cluster.entered_lines(
            self.platform_usage_service.namespace_capacity(now),
            storage_requested=cluster.storage_committed(claims) if claims is not None else None,
            pods_counted=cluster.pods_committed(pods) if pods is not None else None,
            storage_ceiling=ceilings.requests_storage_bytes,
            pods_ceiling=ceilings.pods,
        )
