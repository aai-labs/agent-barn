"""Agent Resource Usage: how much CPU and memory an Agent's container is using.

Read from Prometheus, which scrapes the figures each Agent's healthz server reads from
its own cgroup (see `docs/features/resource-usage.md`). Nothing here is stored, so these
are read models only. This is container usage, not model usage or spend.
"""

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Query, status
from pydantic import BaseModel as PydanticBaseModel

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.platform_admin.models import StatsPeriod
from api.domains.rbac.catalog import PermissionKey

# Prometheus keeps 15 days, so a window reaches back no further.
USAGE_RETENTION = timedelta(days=15)
DEFAULT_USAGE_SPAN = timedelta(hours=24)

# A window is drawn at the finest of these steps that keeps it at or under the point cap.
_USAGE_STEPS_SECONDS = (60, 120, 300, 1800, 3600)
_MAX_POINTS = 360

# The cap on the agents overview. Its queries and its per-row health polling grow with
# the page, so a bounded page is a deliberate limit, and `total` reports the rest. The cap
# keeps the Agents that spent the most, so a page that opens sorted by spend shows them.
OVERVIEW_MAX_AGENTS = 100


@dataclass(frozen=True)
class UsageWindow:
    """A chart window with both ends aligned to the step.

    Aligned so that repeated polls ask for the same points; a moving start would shift
    every bucket on each refresh and make the chart wobble.
    """

    start: datetime
    end: datetime
    step_seconds: int

    @property
    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())

    def timeline(self) -> list[datetime]:
        return [
            self.start + timedelta(seconds=self.step_seconds * i) for i in range(self.seconds // self.step_seconds + 1)
        ]


def resolve_usage_window(from_date: datetime | None, to_date: datetime | None, now: datetime) -> UsageWindow:
    """The last 24 hours, or the picked dates cut to what Prometheus still holds and to now.

    The response's `from_date` and `to_date` then say what was read. Naive datetimes are
    read as UTC, as the stats windows read them.
    """

    def as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    end = min(as_utc(to_date), now) if to_date is not None else now
    start = max(as_utc(from_date), now - USAGE_RETENTION) if from_date is not None else end - DEFAULT_USAGE_SPAN
    if start >= end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The window must end after it starts, within the last 15 days.",
        )
    span = (end - start).total_seconds()
    step = next((step for step in _USAGE_STEPS_SECONDS if span / step <= _MAX_POINTS), _USAGE_STEPS_SECONDS[-1])

    def align(moment: datetime) -> datetime:
        return datetime.fromtimestamp(int(moment.timestamp()) // step * step, UTC)

    return UsageWindow(start=align(start), end=align(end), step_seconds=step)


def get_usage_window(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
) -> UsageWindow:
    return resolve_usage_window(from_date, to_date, datetime.now(UTC))


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
    from_date: datetime
    to_date: datetime
    step_seconds: int
    availability: ResourceUsageAvailability
    # Set only when the source was reachable.
    state: ResourceUsageState | None = None
    observed_at: datetime
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    # What the pod asks for: the share the scheduler and the quota reserve for it. Read from
    # the cluster, not the container, so it can be known when the rest is not, and the other
    # way round. None when it could not be read, which is not a request of zero.
    memory_request_bytes: int | None = None
    memory_peak_bytes: int | None = None
    # A 5-minute average, so a short spike is smoothed away.
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_request_cores: float | None = None
    cpu_average_cores: float | None = None
    # Share of scheduling periods in which the container hit its CPU limit.
    cpu_throttled_ratio: float | None = None
    # One entry per step across the window; a missing reading is null so a gap shows.
    series: list[ResourceUsagePoint] = []


class AgentUsageSnapshotRead(PydanticBaseModel):
    state: ResourceUsageState
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    # As on AgentResourceUsageRead: None when it could not be read.
    memory_request_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_request_cores: float | None = None
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
    # Agents the source scrapes that still run a healthz script from before it reported usage.
    # Their owners report by updating them, which the Platform view says in so many words.
    agents_restart_required: int | None = None
    # Sums over the reporting Agents. A limit is what a container may use, not what it
    # holds, so the limits add up to what the namespace quota counts, not to free room.
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    # What the pods ask for, added up over the same reporting Agents as the limits, so the two
    # describe the same Agents. None when no Agent's request could be read.
    memory_request_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_request_cores: float | None = None


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
    memory_request_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_request_cores: float | None = None
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
    """One Agent's usage over a range, as the Platform page shows it.

    Mirrors the figures the Organization overview's panel shows, field for field, without
    reusing its DTO. `availability` is about the source, `state` about the Agent.
    """

    from_date: datetime
    to_date: datetime
    step_seconds: int
    availability: ResourceUsageAvailability
    state: ResourceUsageState | None = None
    observed_at: datetime
    memory_working_set_bytes: int | None = None
    memory_limit_bytes: int | None = None
    memory_request_bytes: int | None = None
    memory_peak_bytes: int | None = None
    cpu_cores: float | None = None
    cpu_limit_cores: float | None = None
    cpu_request_cores: float | None = None
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
