import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.platform_admin.models import StatsGranularity, StatsPeriod
from api.infrastructure.postgres.models import BaseModel

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class CostRecordSource(str, enum.Enum):
    """Where the spend figure on a row came from.

    ``LITELLM_LIVE`` rows are whatever the proxy reported. ``OPENROUTER_BACKFILL``
    rows were corrected from OpenRouter's generation endpoint and must never be
    overwritten by a later sync pass — see ``CostRepository.upsert_many``.
    """

    LITELLM_LIVE = "litellm_live"
    OPENROUTER_BACKFILL = "openrouter_backfill"


COST_RECORD_STATUS_SUCCESS = "success"

# Rows the healing pass tries to recover: the proxy recorded no money for a
# request that plainly consumed tokens. Kept in sync with the partial index on
# ``CostRecord`` below — widening one without the other silently drops the index.
HEAL_CANDIDATE_PREDICATE = (
    f"spend = 0 AND status = '{COST_RECORD_STATUS_SUCCESS}'"
    f" AND total_tokens > 0 AND source = '{CostRecordSource.LITELLM_LIVE.value}'"
)


class CostRecord(BaseModel, table=True):
    """One LLM call, as billed.

    Identity columns carry no foreign keys on purpose. Cost history is financial
    record-keeping and has to stay queryable after an agent or organization is
    deleted, so the display names are captured here at write time rather than
    joined at read time.

    Only an allowlist of fields from LiteLLM's spend log is copied. Message
    content, request payloads, caller IPs and raw telemetry are deliberately not
    stored (see docs/adr/2026-07-30-platform-oversight-without-organization-access.md).
    """

    __tablename__: str = "cost_record"
    __table_args__ = (
        sa.UniqueConstraint("request_id", name="uq_cost_record_request_id"),
        sa.Index("ix_cost_record_org_occurred", "organization_id", "occurred_at"),
        sa.Index("ix_cost_record_agent_occurred", "agent_id", "occurred_at"),
        sa.Index("ix_cost_record_occurred_at", "occurred_at"),
        sa.Index(
            "ix_cost_record_heal_candidates",
            "occurred_at",
            postgresql_where=sa.text(HEAL_CANDIDATE_PREDICATE),
        ),
    )

    request_id: str = SqlField(nullable=False, max_length=255)
    litellm_key_hash: str = SqlField(nullable=False, max_length=128)

    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    ended_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )

    # NUMERIC, not float: this is billing data. Exact equality against the
    # provider's figure is the only way to tell "we healed it" from "close enough".
    spend: Decimal = SqlField(sa_column=Column(sa.Numeric(20, 12), nullable=False))

    prompt_tokens: int = SqlField(default=0, nullable=False)
    completion_tokens: int = SqlField(default=0, nullable=False)
    total_tokens: int = SqlField(default=0, nullable=False)

    model: str = SqlField(nullable=False, max_length=255)
    status: str = SqlField(nullable=False, max_length=32)
    call_type: str | None = SqlField(default=None, nullable=True, max_length=64)
    request_duration_ms: int | None = SqlField(default=None, nullable=True)

    agent_id: UUID | None = SqlField(default=None, nullable=True)
    organization_id: UUID | None = SqlField(default=None, nullable=True)
    agent_name: str | None = SqlField(default=None, nullable=True, max_length=255)
    organization_name: str | None = SqlField(default=None, nullable=True, max_length=255)

    source: CostRecordSource = SqlField(
        default=CostRecordSource.LITELLM_LIVE,
        sa_column=Column(sa.String(32), nullable=False),
    )
    healed_at: datetime | None = SqlField(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=True,
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AgentModelBreakdown(PydanticBaseModel):
    model: str
    total_cost: float
    prompt_tokens: int
    completion_tokens: int


class AgentCostRead(PydanticBaseModel):
    """Cost totals for a single agent."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: UUID
    agent_name: str
    model: str
    status: str
    total_cost: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    models_breakdown: list[AgentModelBreakdown] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class CostSortDirection(str, enum.Enum):
    NEWEST_FIRST = "newest_first"
    OLDEST_FIRST = "oldest_first"
    MOST_EXPENSIVE = "most_expensive"


class CostFilter(PydanticBaseModel):
    """Narrowing dimensions shared by the row list and every aggregate.

    The same filter drives both, so a stat card and the table under it can never
    disagree about what is being counted.

    `organization_id` is set by the route, never by the caller: on the org surface it
    is pinned to the caller's org, and on the platform surface it is the admin's
    chosen filter. Keeping it here means one query builder serves both.
    """

    organization_id: UUID | None = None
    agent_id: UUID | None = None
    model: str | None = None
    search: str | None = None
    sort: CostSortDirection = CostSortDirection.NEWEST_FIRST


def get_cost_filter(
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort: CostSortDirection = Query(default=CostSortDirection.NEWEST_FIRST),
) -> CostFilter:
    return CostFilter(agent_id=agent_id, model=model, search=search, sort=sort)


def get_platform_cost_filter(
    organization_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort: CostSortDirection = Query(default=CostSortDirection.NEWEST_FIRST),
) -> CostFilter:
    """Same filter, plus the organization dimension only a platform admin may choose."""
    return CostFilter(
        organization_id=organization_id,
        agent_id=agent_id,
        model=model,
        search=search,
        sort=sort,
    )


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------
#
# Cost is stored as NUMERIC and read out as float. Exactness matters when deciding
# whether a row still needs healing; it does not matter for a number rendered to a
# few decimal places. Measured drift across 40,674 production rows was 8e-13.


class CostRecordRead(PydanticBaseModel):
    """One billed LLM call, as an organization sees it."""

    model_config = ConfigDict(from_attributes=True)

    request_id: str
    occurred_at: datetime
    spend: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    status: str
    request_duration_ms: int | None = None
    agent_id: UUID | None = None
    agent_name: str | None = None
    # True when the figure was recovered from OpenRouter rather than reported by the
    # proxy. Worth showing: it explains why a historical total can go up.
    healed: bool = False


class PlatformCostRecordRead(CostRecordRead):
    """The platform admin's view of a call.

    A separate type rather than an optional field on the org one, per the oversight
    ADR's dedicated-read-model rule: the org surface must not be able to return an
    organization name by accident.
    """

    organization_id: UUID | None = None
    organization_name: str | None = None


class CostSeriesPoint(PydanticBaseModel):
    bucket: datetime
    spend: float
    calls: int


class AgentSpendSeriesPoint(PydanticBaseModel):
    bucket: datetime
    agent_id: UUID | None = None
    agent_name: str | None = None
    spend: float


class TokenSeriesPoint(PydanticBaseModel):
    bucket: datetime
    avg_prompt_tokens: float


class CostHistogramBucket(PydanticBaseModel):
    """One bar of the cost-per-call distribution.

    `upper` is None for the final open-ended bucket — a handful of very expensive
    calls is exactly what this chart exists to show, and clamping them would hide it.
    """

    lower: float
    upper: float | None
    calls: int


class CostFilterOption(PydanticBaseModel):
    """One selectable value, already labelled for display."""

    value: str
    label: str


class CostSummaryRead(PydanticBaseModel):
    """Everything above the table on the org cost page, under the same filter."""

    # The resolved window, echoed back. The charts cannot label a bucket without
    # knowing the resolution it was grouped at, and a client that asked for a preset
    # needs the dates it turned into.
    period: StatsPeriod | None = None
    from_date: datetime
    to_date: datetime
    granularity: StatsGranularity

    total_spend: float
    total_calls: int
    active_agents: int
    top_model: str | None = None
    top_model_spend: float = 0.0
    avg_cost_per_call: float = 0.0
    avg_prompt_tokens: float = 0.0
    spend_over_time: list[CostSeriesPoint] = Field(default_factory=list)
    avg_prompt_tokens_over_time: list[TokenSeriesPoint] = Field(default_factory=list)
    spend_by_agent_over_time: list[AgentSpendSeriesPoint] = Field(default_factory=list)
    cost_per_call_histogram: list[CostHistogramBucket] = Field(default_factory=list)


class OrganizationSpendRead(PydanticBaseModel):
    """One organization's slice of platform spend.

    `organization_id` is None for the unattributed bucket, which is kept in the
    ranking rather than filtered out: hiding it would let the platform total silently
    exceed the sum of the rows shown beneath it.
    """

    organization_id: UUID | None = None
    organization_name: str | None = None
    spend: float
    calls: int
    agents: int


class PlatformCostSummaryRead(CostSummaryRead):
    """The org summary plus the figures only a platform admin sees."""

    # Spend over the window divided by its length in days.
    daily_burn_rate: float = 0.0
    # Credit left on the OpenRouter key. None means either no credit limit is set or
    # the poll failed — both are "we don't know", and neither should render as a number.
    credits_remaining: float | None = None
    # Days of credit left at the current burn rate. None whenever either input is
    # unknown or nothing has been spent.
    runway_days: float | None = None
    unattributed_spend: float = 0.0
    unattributed_calls: int = 0
    organizations: list[OrganizationSpendRead] = Field(default_factory=list)
