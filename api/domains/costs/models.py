from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class AgentCostSnapshot(BaseModel, table=True):
    """Preserves per-agent cost data so it survives agent deletion."""

    __tablename__: str = "agent_cost_snapshot"

    __table_args__ = (
        sa.Index("ix_agent_cost_snapshot_organization_id", "organization_id"),
        sa.Index("ix_agent_cost_snapshot_agent_id", "agent_id"),
        sa.Index("ix_agent_cost_snapshot_snapshotted_at", "snapshotted_at"),
    )

    # No FK to agent — the agent may already be deleted when we read this.
    agent_id: UUID = SqlField(nullable=False)
    agent_name: str = SqlField(nullable=False, max_length=255)

    organization_id: UUID = SqlField(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )

    model: str = SqlField(nullable=False, max_length=255)
    total_cost: float = SqlField(nullable=False, default=0.0)
    total_tokens: int = SqlField(nullable=False, default=0)
    prompt_tokens: int = SqlField(nullable=False, default=0)
    completion_tokens: int = SqlField(nullable=False, default=0)

    snapshotted_at: datetime = SqlField(
        nullable=False,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )

    # Store per-model breakdown as JSON string
    models_breakdown_json: str | None = SqlField(nullable=True, default=None)

    def get_models_breakdown(self) -> list[dict]:
        import json

        if not self.models_breakdown_json:
            return []
        try:
            return json.loads(self.models_breakdown_json)
        except Exception:
            return []


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
