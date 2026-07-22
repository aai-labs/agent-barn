from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field


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
