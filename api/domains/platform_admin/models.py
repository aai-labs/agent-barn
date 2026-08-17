"""Platform Oversight read models for the Platform View stats surface (AF-256).

Dedicated read models per the Platform oversight boundary ADR
(`docs/adr/2026-07-30-platform-oversight-without-organization-access.md`): no
Organization-scoped DTO is reused, and only bounded activity statistics are
exposed. Message content, sender/channel/session identity, and any other tenant
content stay out of these contracts by construction — these carry counts only.
"""

import enum
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Query, status
from pydantic import BaseModel

from api.domains.agents.models import AgentPlatform


class StatsPeriod(str, enum.Enum):
    """Reporting windows fixed by the AF-235 backlog: 7, 30, and 90 days."""

    SEVEN_DAYS = "SEVEN_DAYS"
    THIRTY_DAYS = "THIRTY_DAYS"
    NINETY_DAYS = "NINETY_DAYS"

    @property
    def days(self) -> int:
        return _PERIOD_DAYS[self]


_PERIOD_DAYS = {
    StatsPeriod.SEVEN_DAYS: 7,
    StatsPeriod.THIRTY_DAYS: 30,
    StatsPeriod.NINETY_DAYS: 90,
}


class StatsGranularity(str, enum.Enum):
    """Bucket size for the series.

    The value doubles as the postgres `date_trunc` unit and the
    `generate_series` step, so it must stay lowercase and valid for both.
    """

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"

    @property
    def interval(self) -> str:
        return f"1 {self.value}"


# An hour bucket over a one-hour window is a single bar, and a day bucket over
# two years is 730 of them. These thresholds keep a series legible at both ends.
_MINUTE_MAX_HOURS = 2
_HOURLY_MAX_DAYS = 3
_DAILY_MAX_DAYS = 90

# generate_series emits one row per bucket and the response carries one object
# per bucket, so an unbounded span pinned to a fine granularity is a self-service
# denial of service. Well above anything the UI asks for (a year of days is 366).
_MAX_BUCKETS = 5000

_GRANULARITY_SECONDS = {
    StatsGranularity.MINUTE: 60,
    StatsGranularity.HOUR: 3600,
    StatsGranularity.DAY: 86400,
    StatsGranularity.WEEK: 604800,
}


def _auto_granularity(start: datetime, end: datetime) -> StatsGranularity:
    span_seconds = (end - start).total_seconds()
    if span_seconds <= _MINUTE_MAX_HOURS * 3600:
        return StatsGranularity.MINUTE
    span_days = span_seconds / 86400
    if span_days <= _HOURLY_MAX_DAYS:
        return StatsGranularity.HOUR
    if span_days <= _DAILY_MAX_DAYS:
        return StatsGranularity.DAY
    return StatsGranularity.WEEK


class StatsWindow(BaseModel):
    """The resolved reporting window every aggregate runs against.

    Either a preset period or an explicit custom range collapses to the same
    half-open [start, end) interval, so the repositories never need to know
    which one the caller asked for. `period` is None for a custom range — the
    response echoes both, so a client can tell a preset from a range.

    `granularity` is derived from the span unless the caller pins it, and every
    bucket boundary is UTC.
    """

    start: datetime
    end: datetime
    period: StatsPeriod | None
    granularity: StatsGranularity


def resolve_stats_window(
    period: StatsPeriod = StatsPeriod.THIRTY_DAYS,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    granularity: StatsGranularity | None = None,
) -> StatsWindow:
    """Resolve the reporting window.

    Supplying either bound switches to a custom range and `period` is ignored;
    an omitted bound falls back to the period length for `from_date` and to now
    for `to_date`. Naive datetimes are read as UTC, since every stored timestamp
    is timestamptz and the buckets are UTC days.

    Kept separate from the dependency below so it has real Python defaults —
    calling a FastAPI dependency directly leaves `Query(...)` sentinels sitting
    in the parameters, which fails in confusing ways away from a request.
    """
    now = datetime.now(UTC)

    def as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    if from_date is None and to_date is None:
        start, end, resolved_period = now - timedelta(days=period.days), now, period
    else:
        end = as_utc(to_date) if to_date is not None else now
        start = as_utc(from_date) if from_date is not None else end - timedelta(days=period.days)
        resolved_period = None

    if start >= end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_date must be earlier than to_date",
        )

    resolved_granularity = granularity or _auto_granularity(start, end)
    buckets = (end - start).total_seconds() / _GRANULARITY_SECONDS[resolved_granularity]
    if buckets > _MAX_BUCKETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"That range needs {int(buckets):,} {resolved_granularity.value} buckets, "
                f"over the {_MAX_BUCKETS:,} limit. Shorten the range or use a coarser granularity."
            ),
        )

    return StatsWindow(
        start=start,
        end=end,
        period=resolved_period,
        granularity=resolved_granularity,
    )


def get_stats_window(
    period: StatsPeriod = Query(default=StatsPeriod.THIRTY_DAYS),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    granularity: StatsGranularity | None = Query(default=None),
) -> StatsWindow:
    return resolve_stats_window(period, from_date, to_date, granularity)


class PlatformStatsFilter(BaseModel):
    """Narrowing dimensions for both stats surfaces.

    Every dimension is an Agent-owned fact the Platform Oversight boundary
    already allows (Organization, Agent identity, creator, chat platform).
    There is deliberately no filter on who sent a message: `sender_id` is a
    chat-platform identity, and the oversight ADR excludes sender, channel, and
    session identities from these projections.
    """

    organization_id: UUID | None = None
    agent_id: UUID | None = None
    created_by_user_id: UUID | None = None
    platform: AgentPlatform | None = None


def get_platform_stats_filter(
    organization_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    created_by_user_id: UUID | None = Query(default=None),
    platform: AgentPlatform | None = Query(default=None),
) -> PlatformStatsFilter:
    return PlatformStatsFilter(
        organization_id=organization_id,
        agent_id=agent_id,
        created_by_user_id=created_by_user_id,
        platform=platform,
    )


class PlatformMessageSeriesPoint(BaseModel):
    """One bucket of chat volume, keyed by its UTC start instant."""

    bucket: datetime
    inbound: int
    outbound: int


class PlatformMessageStatsRead(BaseModel):
    observed_at: datetime
    period: StatsPeriod | None
    from_date: datetime
    to_date: datetime
    granularity: StatsGranularity
    inbound: int
    outbound: int
    total: int
    series: list[PlatformMessageSeriesPoint]


class PlatformAgentSeriesPoint(BaseModel):
    """One UTC day bucket of Agent inventory and activity.

    `existing` is how many Agents were live at the end of that day and `created`
    is how many were added during it — both reconstructed exactly from
    created_at/deleted_at.

    `active` is how many did observable work that day: sent or received a
    message, or ran a tool. It is measured from telemetry rather than from
    lifecycle events, so it answers "did this Agent do anything" rather than
    "was its deployment meant to be up". Activity is always a lower bound on
    running — an idle Agent that is up all day is active on none of them.
    """

    bucket: datetime
    existing: int
    created: int
    active: int


class PlatformAgentStatsRead(BaseModel):
    """Agent inventory and activity.

    Three deliberately separate numbers rather than one ambiguous "active":

    - `total` — every Agent not soft-deleted, right now.
    - `running` / `stopped` / `errored` — the current status split, right now.
      Read from the Agent row, so they reflect the last recorded state rather
      than liveness: an Agent whose pod died without anyone stopping it still
      counts as running. The three partition `total`.
    - `active` — Agents with observable telemetry anywhere in the period. This is
      the honest activity measure, and the one the series tracks.
    """

    observed_at: datetime
    period: StatsPeriod | None
    from_date: datetime
    to_date: datetime
    granularity: StatsGranularity
    total: int
    running: int
    stopped: int
    errored: int
    active: int
    series: list[PlatformAgentSeriesPoint]
