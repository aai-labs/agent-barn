import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class HonchoUsageEvent(BaseModel, table=True):
    """One model or embedding call Honcho made, attributed to a workspace.

    Honcho sends every model call to LiteLLM on a single service credential and
    carries no workspace identity on the request, so LiteLLM cannot split that
    spend. It does, however, emit per-call telemetry that names the workspace and
    counts tokens. These rows are that telemetry: they carry no money, only the
    token shares used to divide LiteLLM's authoritative total for Honcho's key.
    """

    __tablename__: str = "honcho_usage_event"

    __table_args__ = (
        # Honcho retries a failed batch, so the same CloudEvent can arrive twice.
        sa.UniqueConstraint("event_id", name="uq_honcho_usage_event_event_id"),
        sa.Index("ix_honcho_usage_event_workspace_occurred", "workspace_name", "occurred_at"),
    )

    # CloudEvent id, used only to discard retried duplicates.
    event_id: str = SqlField(nullable=False, max_length=255)
    # `af-<agent id>`; resolved to an Agent when the usage is read, not on write,
    # so ingest never blocks on a lookup and usage for a deleted Agent still lands.
    workspace_name: str = SqlField(nullable=False, max_length=255)
    event_type: str = SqlField(nullable=False, max_length=100)
    model: str = SqlField(nullable=False, max_length=255)
    # Which Honcho subsystem made the call (deriver, dialectic, summary, dream).
    call_purpose: str | None = SqlField(default=None, nullable=True, max_length=100)
    input_tokens: int = SqlField(default=0, nullable=False)
    output_tokens: int = SqlField(default=0, nullable=False)
    occurred_at: datetime.datetime = SqlField(sa_type=sa.DateTime(timezone=True), nullable=False)  # type: ignore


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
    # This Agent's share of Honcho's spend. Zero when memory is off, and separate
    # from total_cost because it is not spent on the Agent's own runtime key —
    # it is the Agent's measured share of one fleet-wide memory credential.
    memory_cost: float = 0.0
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
    # Memory spend for this Organization's Agents only, not the fleet total.
    total_memory_cost: float = Field(default=0.0, alias="totalMemoryCost")
    agents: list[AgentCostRead]
    by_model: list[CostByModelRead] = Field(alias="byModel")
    time_series: list[CostTimeSeriesPoint] = Field(alias="timeSeries")

    model_config = ConfigDict(populate_by_name=True)
