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


class CoreServiceRead(PydanticBaseModel):
    """A Deployment or StatefulSet of the platform itself, not an Agent's."""

    name: str
    kind: str
    desired_replicas: int
    ready_replicas: int
    level: HealthLevel


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
    restart_count: int = 0
    repeatedly_restarting: bool = False
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


class EnvironmentHealthRead(PydanticBaseModel):
    observed_at: datetime
    namespace: str
    level: HealthLevel
    sources: list[EnvironmentSourceRead] = Field(default_factory=list)
    # The quota ceilings as entered, so the page can edit them whichever source `capacity` used.
    ceilings: ResourceLimitsRead = Field(default_factory=ResourceLimitsRead)
    services: list[CoreServiceRead] = Field(default_factory=list)
    alerts: list[FiringAlertRead] = Field(default_factory=list)
    capacity: list[CapacityLineRead] = Field(default_factory=list)
    volumes: VolumeAllocationRead = Field(default_factory=VolumeAllocationRead)
    workloads: WorkloadsRead = Field(default_factory=WorkloadsRead)
    unhealthy_runtimes: list[UnhealthyRuntimeRead] = Field(default_factory=list)
    failed_agents: list[FailedAgentRead] = Field(default_factory=list)
    events: list[WarningEventRead] = Field(default_factory=list)
