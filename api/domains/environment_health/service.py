import logging
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID

from injector import inject, singleton
from kubernetes.client import V1PersistentVolumeClaim, V1Pod, V1ResourceQuota, V1Service
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from api.domains.activity.service import ActivityService
from api.domains.agents.models import PlatformAgentIdentity
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.service import ConversationService
from api.domains.environment_health import cluster
from api.domains.environment_health.models import (
    CapacityLevel,
    CapacityLineRead,
    CoreServiceRead,
    CronJobRead,
    CronJobState,
    DeployedVersionRead,
    EnvironmentHealthRead,
    EnvironmentSource,
    EnvironmentSourceRead,
    FailedAgentRead,
    FiringAlertRead,
    HealthLevel,
    IdleAgentRead,
    ListTotalsRead,
    RolloutState,
    ScheduledBackupsRead,
    SourceState,
    UnhealthyRuntimeRead,
    VolumeAllocationRead,
    WarningEventRead,
    WorkloadsRead,
)
from api.domains.environment_health.repository import EnvironmentHealthRepository
from api.domains.resource_limits.models import ResourceLimitsRead
from api.domains.resource_limits.service import ResourceLimitsService
from api.domains.resource_usage.models import NamespacePeaksRead, PlatformCapacityRead
from api.domains.resource_usage.platform_service import PlatformResourceUsageService
from api.domains.restore_points.service import RestorePointService
from api.infrastructure.prometheus.client import PrometheusError

logger = logging.getLogger(__name__)

# How far back each capacity line's peak looks: long enough to hold a day of cron schedules.
PEAK_WINDOW_HOURS = 24
RESTART_WINDOW_DAYS = cluster.RESTART_HISTORY_WINDOW.days
# How far back a failed scheduled backup is news.
BACKUP_FAILURE_WINDOW_HOURS = 24
# How long with no message from a person before a running or stopped Agent is a cleanup candidate.
IDLE_AFTER_DAYS = 14

T = TypeVar("T")

# One thread per cluster read and Prometheus query, so none waits on another.
_READ_WORKERS = 16


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
    volumes: VolumeAllocationRead,
    events: Sequence[WarningEventRead],
    deployed: DeployedVersionRead | None,
    cron_jobs: Sequence[CronJobRead],
    backups: ScheduledBackupsRead,
) -> HealthLevel:
    """The worst of what the page shows.

    Critical when a platform service has no ready replica, a quota line is at or past 90%,
    or a critical alert is firing. A warning for anything else that needs a look, and when
    Prometheus could not answer, since a critical alert may be firing unseen, and when some
    services are left on an older build with no rollout under way. Unknown when
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
        sources.get(EnvironmentSource.PROMETHEUS) == SourceState.UNAVAILABLE
        or any(service.level == HealthLevel.WARNING for service in services)
        or any(line.level in {CapacityLevel.WARNING, CapacityLevel.CEILING_OUT_OF_DATE} for line in capacity)
        or workloads.issues
        or unhealthy_runtimes
        or failed_agents
        or alerts
        or volumes.attention
        or events
        or backups.failed_total
        or backups.overdue_total
        or any(cron.state in {CronJobState.FAILING, CronJobState.STALLED} for cron in cron_jobs)
        or (
            deployed is not None and deployed.mixed and not any(s.rollout == RolloutState.IN_PROGRESS for s in services)
        )
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
    restore_point_service: RestorePointService
    conversation_service: ConversationService
    activity_service: ActivityService

    def get_health(self) -> EnvironmentHealthRead:
        now = datetime.now(UTC)
        sources: dict[EnvironmentSource, SourceState] = {}
        identities = cluster.identities_by_id(self.agent_repository.find_live_for_platform_usage())

        def settle(source: EnvironmentSource, read: Future[T]) -> T | None:
            try:
                value = read.result()
            except Exception as error:
                state = _state_of(error)
                if state == SourceState.UNAVAILABLE:
                    logger.warning("Environment health source %s is unavailable", source.value, exc_info=True)
                sources[source] = state
                return None
            sources[source] = SourceState.AVAILABLE
            return value

        def query(read: Future[T], what: str) -> T | None:
            try:
                return read.result()
            except PrometheusError:
                logger.warning("Environment health cannot read %s from Prometheus", what, exc_info=True)
                sources[EnvironmentSource.PROMETHEUS] = SourceState.UNAVAILABLE
                return None

        repository = self.repository
        prometheus = repository.prometheus_configured
        # Every cluster and Prometheus read at once: each waits on the network, and one after
        # another they would add up to the page's load time.
        with ThreadPoolExecutor(max_workers=_READ_WORKERS, thread_name_prefix="environment-health") as pool:
            pods_read = pool.submit(repository.pods)
            deployments_read = pool.submit(repository.deployments)
            stateful_sets_read = pool.submit(repository.stateful_sets)
            replica_sets_read = pool.submit(repository.replica_sets)
            claims_read = pool.submit(repository.volume_claims)
            kube_services_read = pool.submit(repository.services)
            crons_read = pool.submit(repository.cron_jobs)
            jobs_read = pool.submit(repository.jobs)
            quotas_read = pool.submit(repository.resource_quotas)
            events_read = pool.submit(repository.warning_events)
            if prometheus:
                alerts_read = pool.submit(repository.firing_alerts, at=now)
                runtime_read = pool.submit(repository.runtime_health, at=now)
                restarts_read = pool.submit(repository.restart_history, at=now, window_days=RESTART_WINDOW_DAYS)
            peaks_read = pool.submit(self.platform_usage_service.namespace_peaks, now, window_hours=PEAK_WINDOW_HOURS)
            usage_read = pool.submit(self.platform_usage_service.namespace_capacity, now)

            pods = settle(EnvironmentSource.PODS, pods_read)
            deployments = settle(EnvironmentSource.DEPLOYMENTS, deployments_read)
            stateful_sets = settle(EnvironmentSource.STATEFUL_SETS, stateful_sets_read)
            replica_sets = settle(EnvironmentSource.REPLICA_SETS, replica_sets_read)
            claims = settle(EnvironmentSource.VOLUME_CLAIMS, claims_read)
            kube_services = settle(EnvironmentSource.SERVICES, kube_services_read)
            crons = settle(EnvironmentSource.CRON_JOBS, crons_read)
            jobs = settle(EnvironmentSource.JOBS, jobs_read)
            quotas = settle(EnvironmentSource.RESOURCE_QUOTAS, quotas_read)
            events = settle(EnvironmentSource.EVENTS, events_read)

            alert_samples = runtime_samples = restart_samples = None
            if not prometheus:
                sources[EnvironmentSource.PROMETHEUS] = SourceState.NOT_CONFIGURED
            else:
                # Each query on its own, so a failed runtime query still keeps the alerts that loaded.
                sources[EnvironmentSource.PROMETHEUS] = SourceState.AVAILABLE
                alert_samples = query(alerts_read, "firing alerts")
                runtime_samples = query(runtime_read, "runtime health")
                restart_samples = query(restarts_read, "restart history")
            peaks = peaks_read.result()
            usage = usage_read.result()

        services = cluster.core_services(deployments or [], stateful_sets or [], replica_sets)
        deployed = cluster.deployed_version(services)
        cron_jobs = cluster.cron_jobs(crons, jobs or [], now) if crons is not None else []
        backups = cluster.scheduled_backups(
            self.restore_point_service.scheduled_backup_health(
                now, failure_window=timedelta(hours=BACKUP_FAILURE_WINDOW_HOURS)
            ),
            identities,
            failure_window_hours=BACKUP_FAILURE_WINDOW_HOURS,
        )
        restarts = cluster.pod_restarts(restart_samples) if restart_samples is not None else None
        workloads = cluster.workloads(pods, identities, now, restarts) if pods is not None else WorkloadsRead()
        if jobs is not None:
            workloads = cluster.without_cron_runs(workloads, cluster.finished_cron_runs(jobs))
        alerts = cluster.firing_alerts(alert_samples or [], identities)
        unhealthy = cluster.unhealthy_runtimes(
            runtime_samples or [], identities, cluster.agent_pod_readiness(pods or [])
        )
        failed = cluster.failed_agents(self.agent_repository.find_failed_for_platform())
        idle = self._idle_agents(now, identities, pods, claims)
        ceilings = self.resource_limits_service.get_limits()
        capacity = self._capacity(ceilings, peaks, usage, quotas, claims, pods, kube_services)
        volumes = cluster.volume_allocation(claims or [], identities)
        owners = cluster.workload_owners(
            deployments=deployments or [],
            stateful_sets=stateful_sets or [],
            cron_jobs=crons or [],
            replica_sets=replica_sets or [],
            jobs=jobs or [],
            pods=pods or [],
        )
        warnings = cluster.warning_events(events or [], identities, now, owners=owners)
        limit = cluster.LIST_LIMIT

        return EnvironmentHealthRead(
            observed_at=now,
            namespace=self.repository.namespace,
            peak_window_hours=PEAK_WINDOW_HOURS,
            restart_window_days=RESTART_WINDOW_DAYS,
            level=overall_level(
                sources=sources,
                services=services,
                capacity=capacity,
                workloads=workloads,
                unhealthy_runtimes=unhealthy,
                failed_agents=failed,
                alerts=alerts,
                volumes=volumes,
                events=warnings,
                deployed=deployed,
                cron_jobs=cron_jobs,
                backups=backups,
            ),
            sources=[EnvironmentSourceRead(source=source, state=state) for source, state in sources.items()],
            deployed=deployed,
            ceilings=ceilings,
            services=services,
            cron_jobs=cron_jobs,
            backups=backups,
            alerts=alerts,
            capacity=capacity,
            # The level above is worked out from every row; each list carries the worst `limit`.
            volumes=volumes.model_copy(update={"attention": volumes.attention[:limit]}),
            workloads=workloads.model_copy(update={"issues": workloads.issues[:limit]}),
            unhealthy_runtimes=unhealthy[:limit],
            failed_agents=failed[:limit],
            idle_agents=idle[:limit],
            idle_after_days=IDLE_AFTER_DAYS,
            events=warnings[:limit],
            totals=ListTotalsRead(
                failed_agents=len(failed),
                unhealthy_runtimes=len(unhealthy),
                pod_issues=len(workloads.issues),
                idle_agents=len(idle),
                volume_claims=len(volumes.attention),
                events=len(warnings),
            ),
        )

    def _idle_agents(
        self,
        now: datetime,
        identities: dict[UUID, PlatformAgentIdentity],
        pods: list[V1Pod] | None,
        claims: list[V1PersistentVolumeClaim] | None,
    ) -> list[IdleAgentRead]:
        """Cleanup candidates. Every read is of the database except what each one holds in the cluster."""
        candidates = [agent_id for agent_id, identity in identities.items() if identity.status in cluster.IDLE_STATUSES]
        return cluster.idle_agents(
            identities,
            last_user_message=self.conversation_service.latest_inbound_times_for_platform(candidates),
            last_call=self.activity_service.latest_call_times_for_platform(candidates),
            pods=pods,
            claims=claims,
            restore_points=self.restore_point_service.ready_totals_for_platform(candidates),
            now=now,
            idle_after=timedelta(days=IDLE_AFTER_DAYS),
        )

    def _capacity(
        self,
        ceilings: ResourceLimitsRead,
        peaks: NamespacePeaksRead,
        usage: PlatformCapacityRead,
        quotas: list[V1ResourceQuota] | None,
        claims: list[V1PersistentVolumeClaim] | None,
        pods: list[V1Pod] | None,
        kube_services: list[V1Service] | None,
    ) -> list[CapacityLineRead]:
        """The namespace's quota when it can be read, otherwise the ceilings entered by hand.

        The tenant account has no `resourcequotas` rule today, so the entered ceilings are the
        usual answer (see `docs/adr/2026-10-01-capacity-limits-entered-by-hand.md`). Once the
        cluster's owners grant the read, the quota's own figures take over with no change here.
        """
        by_resource = {
            "limits.memory": cluster.as_float(peaks.limits_memory_bytes),
            "requests.memory": cluster.as_float(peaks.requests_memory_bytes),
            "limits.cpu": peaks.limits_cpu_cores,
            "requests.cpu": peaks.requests_cpu_cores,
            "pods": cluster.as_float(peaks.pods),
        }
        if quotas:
            return cluster.with_peaks(cluster.quota_lines(quotas), by_resource)
        lines = cluster.entered_lines(
            usage,
            storage_requested=cluster.storage_committed(claims) if claims is not None else None,
            pods_counted=cluster.pods_committed(pods) if pods is not None else None,
            storage_ceiling=ceilings.requests_storage_bytes,
            pods_ceiling=ceilings.pods,
            claims_counted=len(claims) if claims is not None else None,
            claims_ceiling=ceilings.persistentvolumeclaims,
            services_counted=cluster.services_committed(kube_services) if kube_services is not None else None,
            services_ceiling=ceilings.services,
        )
        return cluster.with_peaks(lines, by_resource)
