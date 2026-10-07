"""Agent Resource Usage: how much CPU and memory an Agent's container is using.

Read from Prometheus, which scrapes the figures each Agent's healthz server reads from
its own cgroup (see `docs/features/resource-usage.md`). Nothing here is stored, so these
are read models only. This is container usage, not model usage or spend.
"""

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.platform_admin.models import StatsPeriod
from api.domains.rbac.catalog import PermissionKey


class ResourceUsageRange(str, enum.Enum):
    """How far back a chart looks. Capped at 14 days: Prometheus keeps 15."""

    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    ONE_DAY = "24h"
    SEVEN_DAYS = "7d"
    FOURTEEN_DAYS = "14d"

    @property
    def seconds(self) -> int:
        return _RANGE_SECONDS[self]

    @property
    def step_seconds(self) -> int:
        return _RANGE_STEP_SECONDS[self]


_RANGE_SECONDS = {
    ResourceUsageRange.ONE_HOUR: 3600,
    ResourceUsageRange.SIX_HOURS: 6 * 3600,
    ResourceUsageRange.ONE_DAY: 24 * 3600,
    ResourceUsageRange.SEVEN_DAYS: 7 * 24 * 3600,
    ResourceUsageRange.FOURTEEN_DAYS: 14 * 24 * 3600,
}

# Each range is drawn with a step that keeps a chart at 60 to 337 points.
_RANGE_STEP_SECONDS = {
    ResourceUsageRange.ONE_HOUR: 60,
    ResourceUsageRange.SIX_HOURS: 120,
    ResourceUsageRange.ONE_DAY: 300,
    ResourceUsageRange.SEVEN_DAYS: 1800,
    ResourceUsageRange.FOURTEEN_DAYS: 3600,
}

# The cap on the agents overview. Its queries and its per-row health polling grow with
# the page, so a bounded page is a deliberate limit, and `total` reports the rest. The cap
# keeps the Agents that spent the most, so a page that opens sorted by spend shows them.
OVERVIEW_MAX_AGENTS = 100


@dataclass(frozen=True)
class UsageWindow:
    """A chart window with its end aligned to the step.

    Aligned so that repeated polls ask for the same points; a moving start would shift
    every bucket on each refresh and make the chart wobble.
    """

    usage_range: ResourceUsageRange
    start: datetime
    end: datetime
    step_seconds: int

    def timeline(self) -> list[datetime]:
        count = int((self.end - self.start).total_seconds()) // self.step_seconds
        return [self.start + timedelta(seconds=self.step_seconds * i) for i in range(count + 1)]


def resolve_usage_window(usage_range: ResourceUsageRange, now: datetime) -> UsageWindow:
    step = usage_range.step_seconds
    end = datetime.fromtimestamp(int(now.timestamp()) // step * step, UTC)
    return UsageWindow(
        usage_range=usage_range,
        start=end - timedelta(seconds=usage_range.seconds),
        end=end,
        step_seconds=step,
    )


class ResourceUsageAvailability(str, enum.Enum):
    """Whether the numbers could be fetched at all. About the source, not the Agent."""

    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"


class ResourceUsageState(str, enum.Enum):
    """What the source knows about one Agent."""

    REPORTING = "reporting"
    # Scraped, but still running a healthz script from before it reported usage.
    RESTART_REQUIRED = "restart_required"
    # The container cannot read its cgroup v2 files (an older node).
    UNSUPPORTED = "unsupported"
    NO_DATA = "no_data"


class ResourceUsagePoint(PydanticBaseModel):
    bucket: datetime
    memory_working_set_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_throttled_ratio: float | None = None


class AgentResourceUsageRead(PydanticBaseModel):
    agent_id: UUID
    range: ResourceUsageRange
    from_date: datetime
    to_date: datetime
    step_seconds: int
    availability: ResourceUsageAvailability
    # Set only when the source was reachable.
    state: ResourceUsageState | None = None
    observed_at: datetime
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    memory_peak_bytes: int | None = None
    # A 5-minute average, so a short spike is smoothed away.
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_average_cores: float | None = None
    # Share of scheduling periods in which the container hit its CPU limit.
    cpu_throttled_ratio: float | None = None
    # One entry per step across the window; a missing reading is null so a gap shows.
    series: list[ResourceUsagePoint] = []


class AgentUsageSnapshotRead(PydanticBaseModel):
    state: ResourceUsageState
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    # Over the last hour.
    cpu_throttled_ratio: float | None = None


class AgentOverviewSpendRead(PydanticBaseModel):
    spend: float
    calls: int
    last_call_at: datetime | None = None


class AgentOverviewItemRead(PydanticBaseModel):
    id: UUID
    name: str
    status: AgentStatus
    agent_type: AgentType
    effective_model: str
    created_at: datetime
    allowed_actions: list[PermissionKey]
    # None without `cost.read` on this Agent. An Agent with no calls has zero spend.
    spend: AgentOverviewSpendRead | None = None
    # None without `activity.read`, and for a stopped Agent (there is no container).
    resource_usage: AgentUsageSnapshotRead | None = None


class AgentOverviewRead(PydanticBaseModel):
    period: StatsPeriod | None = None
    from_date: datetime
    to_date: datetime
    resource_usage_availability: ResourceUsageAvailability
    # Every Agent the caller can read; `items` stops at OVERVIEW_MAX_AGENTS.
    total: int
    items: list[AgentOverviewItemRead]


# --- Platform view ---------------------------------------------------------------------
# Dedicated read models, per the Platform oversight ADR: none of the Organization-scoped
# ones above is reused, so neither surface can grow a field into the other by accident.


class PlatformUsageTotalsRead(PydanticBaseModel):
    # Live Agents that should have a container: running, or in error (it may be crashing).
    # Read from the database, so it is there even when the source is not.
    agents_with_container: int
    # The rest are None when the source could not be read.
    # Agents whose container reported CPU or memory.
    agents_reporting: int | None = None
    # Sums over the reporting Agents. A limit is what a container may use, not what it
    # holds, so the limits add up to what the namespace quota counts, not to free room.
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None


class PlatformOrganizationUsageRead(PlatformUsageTotalsRead):
    # Both None for containers that report but belong to no live Agent: deleted, or
    # never known to this database.
    organization_id: UUID | None = None
    organization_name: str | None = None


class PlatformAgentUsageRead(PydanticBaseModel):
    agent_id: UUID
    # None when no live Agent has this id; the same goes for the organization.
    agent_name: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    # Over the last hour.
    cpu_throttled_ratio: float | None = None


class PlatformUsagePoint(PydanticBaseModel):
    """All the selected Agents together at one step. A missing reading is null."""

    bucket: datetime
    memory_working_set_bytes: int | None = None
    cpu_cores: float | None = None


class PlatformCapacityRead(PydanticBaseModel):
    """The namespace's ceilings and what is committed against them.

    The ceilings are entered by a Platform Administrator, because the quota itself cannot
    be read; the committed figures come from kube-state-metrics. They are always for the
    whole namespace, whatever Organization the page is narrowed to. A quota caps limits and
    requests alike, and a new pod is refused when any of the four would go over, so all four
    are here, named as the quota names them.
    """

    limits_memory_bytes: int | None = None
    limits_cpu_cores: float | None = None
    requests_memory_bytes: int | None = None
    requests_cpu_cores: float | None = None
    # None until the first save.
    ceilings_updated_at: datetime | None = None
    # What every Pending or Running pod commits, each charged the larger of its containers
    # and its biggest init container, as the quota does. None when it could not be read.
    committed_limits_memory_bytes: int | None = None
    committed_limits_cpu_cores: float | None = None
    committed_requests_memory_bytes: int | None = None
    committed_requests_cpu_cores: float | None = None


class PlatformResourceUsageRead(PydanticBaseModel):
    range: ResourceUsageRange
    from_date: datetime
    to_date: datetime
    step_seconds: int
    observed_at: datetime
    availability: ResourceUsageAvailability
    organization_id: UUID | None = None
    # Narrowed to `organization_id` when one is given. The counts come from the database,
    # so they are there even when the source is not.
    totals: PlatformUsageTotalsRead
    # Present even when the source is not: the limits come from the database.
    capacity: PlatformCapacityRead
    # Always the whole platform, whatever the filter, heaviest memory first, with the
    # no-live-Agent row, if any, last. How many of them to show is the page's choice.
    organizations: list[PlatformOrganizationUsageRead] = []
    # Every reporting Agent within the filter, heaviest memory first.
    agents: list[PlatformAgentUsageRead] = []
    series: list[PlatformUsagePoint] = []


class PlatformAgentUsagePoint(PydanticBaseModel):
    """One Agent at one step. A missing reading is null, so a gap shows as a gap."""

    bucket: datetime
    memory_working_set_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_throttled_ratio: float | None = None


class PlatformAgentResourceUsageRead(PydanticBaseModel):
    """One Agent's usage over the last day, as the Platform page shows it.

    Mirrors the figures the Organization overview's panel shows, field for field, without
    reusing its DTO. `availability` is about the source, `state` about the Agent.
    """

    range: ResourceUsageRange
    from_date: datetime
    to_date: datetime
    step_seconds: int
    availability: ResourceUsageAvailability
    state: ResourceUsageState | None = None
    observed_at: datetime
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    memory_peak_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_average_cores: float | None = None
    cpu_throttled_ratio: float | None = None
    series: list[PlatformAgentUsagePoint] = []


class PlatformAgentDetailsRead(PydanticBaseModel):
    """What the Platform page shows when a Heaviest agents row is opened.

    An explicit allowlist, per the Platform oversight ADR: identity and lifecycle, whether
    the Agent is working, restarts and why the last one ended, and its usage. It carries no
    log text, no free-text health reason and no failure detail; the failure summary is fixed
    product copy chosen by category.
    """

    agent_id: UUID
    name: str
    status: AgentStatus
    agent_type: AgentType
    effective_model: str
    created_at: datetime
    organization_id: UUID
    organization_name: str
    # Set for an Agent in ERROR only.
    last_error_summary: str | None = None
    # The word only (ok, initializing, crashed, error, starting); None for a stopped Agent
    # or one whose healthz could not be reached.
    health_status: str | None = None
    # None when the cluster could not be asked, or there is no container.
    restart_count: int | None = None
    termination_reason: str | None = None
    # None for a stopped Agent: there is no container to measure.
    resource_usage: PlatformAgentResourceUsageRead | None = None
