import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

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


class CostByModelRead(PydanticBaseModel):
    """Aggregated cost for one model across all agents."""

    model: str
    total_cost: float


class CostTimeSeriesPoint(PydanticBaseModel):
    """A single data point in a cost time-series chart."""

    date: str
    cost: float


class OrgCostSummaryRead(PydanticBaseModel):
    """Top-level cost summary returned to the frontend."""

    total_cost: float = Field(alias="totalCost")
    agents: list[AgentCostRead]
    by_model: list[CostByModelRead] = Field(alias="byModel")
    time_series: list[CostTimeSeriesPoint] = Field(alias="timeSeries")

    model_config = ConfigDict(populate_by_name=True)
