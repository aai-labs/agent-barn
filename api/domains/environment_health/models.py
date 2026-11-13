"""Read models for the environment health page.

Platform Oversight Data, classified in
`docs/adr/2026-10-20-environment-health-as-platform-oversight-data.md`. Every field is an
explicit allowlist: Kubernetes names that this platform generates, fixed reason words, numbers,
times, and Agents and Organizations named from the database. No free text from the cluster
reaches a client; an Event's message is reduced to a fixed explanation and, for a quota or
LimitRange rejection only, a detail rebuilt from validated fragments.
"""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from api.domains.agents.models import AgentStatus
from api.domains.resource_limits.models import ResourceLimitsRead


class EnvironmentSource(str, enum.Enum):
    """Where a part of the page comes from, so a missing part can say why it is missing."""

    PODS = "pods"
    DEPLOYMENTS = "deployments"
    STATEFUL_SETS = "stateful_sets"
    VOLUME_CLAIMS = "volume_claims"
    SERVICES = "services"
    CRON_JOBS = "cron_jobs"
    JOBS = "jobs"
    RESOURCE_QUOTAS = "resource_quotas"
    EVENTS = "events"
    PROMETHEUS = "prometheus"


class SourceState(str, enum.Enum):
    AVAILABLE = "available"
    # The cluster refused the read (403): the service account has no rule for it.
    FORBIDDEN = "forbidden"
    # The read failed for any other reason: timeout, outage, unexpected answer.
    UNAVAILABLE = "unavailable"
    # No cluster or no Prometheus URL is configured, as in local Docker Compose.
    NOT_CONFIGURED = "not_configured"


class HealthLevel(str, enum.Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class EnvironmentSourceRead(PydanticBaseModel):
    source: EnvironmentSource
    state: SourceState


class AgentRefRead(PydanticBaseModel):
    """An Agent a cluster resource belongs to, named from the database.

    The id comes from a label this platform sets; everything else is looked up by it, never
    taken from a label. With no live Agent behind the id, only the id is known.
    """

    agent_id: UUID
    agent_name: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    status: AgentStatus | None = None


class RolloutState(str, enum.Enum):
    """A Deployment's `Progressing` condition, reduced to what an administrator acts on."""

    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    # The rollout passed its progress deadline: the new pods never became ready.
    STUCK = "stuck"


class CoreServiceRead(PydanticBaseModel):
    """A Deployment or StatefulSet of the platform itself, not an Agent's."""

    name: str
    kind: str
    desired_replicas: int
    ready_replicas: int
    level: HealthLevel
    # The commit the Deployment's pods were built from, from the `build-sha` annotation the
    # charts set. Only a 7 to 40 character hex string is kept.
    build_sha: str | None = None
    rollout: RolloutState | None = None
    # When the last rollout finished. None while one is under way or stuck.
    rolled_out_at: datetime | None = None


class DeployedVersionRead(PydanticBaseModel):
    """The build the platform runs: the one rolled out most recently."""

    build_sha: str
    rolled_out_at: datetime | None = None
    # Some services carry another build, as when one failed to roll out.
    mixed: bool = False
    # The services on another build than `build_sha`.
    behind: list[str] = Field(default_factory=list)


class CronJobState(str, enum.Enum):
    OK = "ok"
    # Its newest run failed.
    FAILING = "failing"
    # No run has succeeded for longer than every platform schedule allows, or none ever has.
    STALLED = "stalled"
    # Switched off on purpose. Not a problem in itself.
    SUSPENDED = "suspended"


class CronJobRead(PydanticBaseModel):
    """One of the platform's scheduled jobs, named as its chart names it."""

    name: str
    # Only a schedule in the cron grammar is kept.
    schedule: str | None = None
    state: CronJobState
    running: bool = False
    last_scheduled_at: datetime | None = None
    last_successful_at: datetime | None = None
    # When its most recent failed run, of those Kubernetes still keeps, failed.
    last_failed_at: datetime | None = None


class BackupFailureRead(PydanticBaseModel):
    """An Agent whose scheduled backups failed in the failure window. The failure text is not carried."""

    agent: AgentRefRead
    failures: int
    last_failed_at: datetime


class OverdueBackupRead(PydanticBaseModel):
    """A running Agent with no successful scheduled backup for two intervals or more."""

    agent: AgentRefRead
    # None when it never had one.
    last_backup_at: datetime | None = None


class ScheduledBackupsRead(PydanticBaseModel):
    """Whether the scheduled backups of running Agents are happening, from the database."""

    enabled: bool = False
    interval_minutes: int = 0
    # The window `failed` covers.
    failure_window_hours: int = 24
    # Running Agents, which are the ones the schedule backs up.
    running_agents: int = 0
    # How many Agents fail or are overdue. When every backup fails at once (a full volume
    # quota, say) that is the news, so only the worst few are named in the lists below.
    failed_total: int = 0
    overdue_total: int = 0
    # Most failures first. An Agent named here is not named again under `overdue`.
    failed: list[BackupFailureRead] = Field(default_factory=list)
    # Never backed up first, then the longest without one.
    overdue: list[OverdueBackupRead] = Field(default_factory=list)


class FiringAlertRead(PydanticBaseModel):
    """A firing alert from the monitoring chart's own rules: its name and severity only."""

    name: str
    severity: str | None = None
    agent: AgentRefRead | None = None


class CapacitySource(str, enum.Enum):
    # Read from the namespace's ResourceQuota: the cluster's own figures.
    QUOTA = "quota"
    # A ceiling a Platform Administrator entered, against what the API counts itself.
    ENTERED = "entered"


class CapacityLevel(str, enum.Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    # Above an entered ceiling. A quota cannot be exceeded, so the ceiling is out of date.
    CEILING_OUT_OF_DATE = "ceiling_out_of_date"
    # No ceiling, or nothing known to compare with it.
    UNKNOWN = "unknown"


class CapacityUnit(str, enum.Enum):
    BYTES = "bytes"
    CORES = "cores"
    COUNT = "count"


class CapacityLineRead(PydanticBaseModel):
    """One quota line, named as the quota names it (`requests.storage`, `pods`, ...)."""

    resource: str
    unit: CapacityUnit
    source: CapacitySource
    used: float | None = None
    hard: float | None = None
    ratio: float | None = None
    # The highest `used` reached over the last `peak_window_hours`, from kube-state-metrics,
    # for the lines it can count (CPU, memory and pods). None when it is not known.
    peak: float | None = None
    peak_ratio: float | None = None
    level: CapacityLevel


class VolumeGroup(str, enum.Enum):
    INFRASTRUCTURE = "infrastructure"
    ACTIVE_AGENTS = "active_agents"
    STOPPED_AGENTS = "stopped_agents"
    RESTORE_POINTS = "restore_points"
    # An Agent's claim with no live Agent behind it. It still counts against the quota.
    ORPHANED = "orphaned"


class VolumeGroupRead(PydanticBaseModel):
    group: VolumeGroup
    claims: int = 0
    requested_bytes: int = 0


class VolumeClaimRead(PydanticBaseModel):
    name: str
    group: VolumeGroup
    # Bound, Pending, Lost or Terminating; anything else reads as None.
    phase: str | None = None
    requested_bytes: int | None = None
    agent: AgentRefRead | None = None
    created_at: datetime | None = None


class VolumeAllocationRead(PydanticBaseModel):
    total_claims: int = 0
    total_requested_bytes: int = 0
    groups: list[VolumeGroupRead] = Field(default_factory=list)
    # Only the claims that need a look: orphaned, or not Bound.
    attention: list[VolumeClaimRead] = Field(default_factory=list)


class WorkloadKind(str, enum.Enum):
    AGENT = "agent"
    RESTORE_POINT = "restore_point"
    INFRASTRUCTURE = "infrastructure"


class PodIssueRead(PydanticBaseModel):
    """A pod that is not ready, has stopped on a known failure, or keeps restarting."""

    pod_name: str
    workload_name: str | None = None
    kind: WorkloadKind
    agent: AgentRefRead | None = None
    phase: str | None = None
    ready: bool
    # Unschedulable: no node has room for it, or none matches it.
    unschedulable: bool = False
    # Restarts since the pod was created. Never reset, so a high count may be old news.
    restart_count: int = 0
    # Restarts within the restart window, from kube-state-metrics. None when not known.
    restarts_in_window: int | None = None
    repeatedly_restarting: bool = False
    # A container ran out of memory within the restart window.
    oom_killed: bool = False
    waiting_reason: str | None = None
    termination_reason: str | None = None
    last_restart_at: datetime | None = None
    created_at: datetime | None = None


class WorkloadsRead(PydanticBaseModel):
    pods_total: int = 0
    pods_ready: int = 0
    issues: list[PodIssueRead] = Field(default_factory=list)


class UnhealthyRuntimeRead(PydanticBaseModel):
    """An Agent whose healthz says its runtime is not working, whatever its pod says."""

    agent: AgentRefRead
    pod_ready: bool | None = None
    # False when the runtime has never connected since the pod started, True when it lost
    # a connection it had, None when the healthz server does not report it.
    ever_connected: bool | None = None


class FailedAgentRead(PydanticBaseModel):
    """An Agent in ERROR with the fixed-copy summary of its stored failure."""

    agent: AgentRefRead
    code: str | None = None
    summary: str | None = None
    # Only a detail matching its category's grammar: a quota line and quantities, a
    # LimitRange bound, a denied verb and resource kind, or a fixed exception name.
    detail: str | None = None
    updated_at: datetime


class WarningEventRead(PydanticBaseModel):
    reason: str
    object_kind: str | None = None
    object_name: str | None = None
    agent: AgentRefRead | None = None
    count: int = 1
    last_seen: datetime | None = None
    explanation: str
    detail: str | None = None


class IdleAgentRead(PydanticBaseModel):
    """A running or stopped Agent no one has written to for `idle_after_days`: a cleanup candidate.

    What it holds is what deleting it would free. A figure that could not be read is None.
    """

    agent: AgentRefRead
    # The newest message a person sent it. None when no one ever has.
    last_user_message_at: datetime | None = None
    # Its newest model call, for context. The platform wakes Agents on its own, so a recent
    # call with no user message does not make an Agent in use.
    last_call_at: datetime | None = None
    holds_pod: bool | None = None
    volume_claims: int | None = None
    requested_bytes: int | None = None
    restore_points: int = 0
    restore_point_bytes: int = 0


class EnvironmentHealthRead(PydanticBaseModel):
    observed_at: datetime
    namespace: str
    level: HealthLevel
    # The window each capacity line's `peak` covers.
    peak_window_hours: int
    # The window a pod's `restarts_in_window` and `oom_killed` cover.
    restart_window_days: int
    sources: list[EnvironmentSourceRead] = Field(default_factory=list)
    # The build the platform's services run, when their Deployments carry one.
    deployed: DeployedVersionRead | None = None
    # The quota ceilings as entered, so the page can edit them whichever source `capacity` used.
    ceilings: ResourceLimitsRead = Field(default_factory=ResourceLimitsRead)
    services: list[CoreServiceRead] = Field(default_factory=list)
    cron_jobs: list[CronJobRead] = Field(default_factory=list)
    backups: ScheduledBackupsRead = Field(default_factory=ScheduledBackupsRead)
    alerts: list[FiringAlertRead] = Field(default_factory=list)
    capacity: list[CapacityLineRead] = Field(default_factory=list)
    volumes: VolumeAllocationRead = Field(default_factory=VolumeAllocationRead)
    workloads: WorkloadsRead = Field(default_factory=WorkloadsRead)
    unhealthy_runtimes: list[UnhealthyRuntimeRead] = Field(default_factory=list)
    failed_agents: list[FailedAgentRead] = Field(default_factory=list)
    idle_agents: list[IdleAgentRead] = Field(default_factory=list)
    # How long without a user message before an Agent is listed in `idle_agents`.
    idle_after_days: int = 14
    events: list[WarningEventRead] = Field(default_factory=list)
