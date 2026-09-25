import enum
from datetime import datetime
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from api.domains.platform_admin.models import StatsGranularity, StatsPeriod

# Calls further apart than this belong to different pieces of work. An agent
# turn fans out into several model calls seconds apart; the next scheduled wake
# is minutes or hours away, so the two never merge at this threshold.
WAKE_GAP_SECONDS = 300

# How long before a wake an inbound message still counts as having caused it.
# A person sends a message, the gateway delivers it, the runtime builds a prompt
# — the first model call lands seconds later, not immediately.
USER_LEAD_SECONDS = 120


class ActivityTrigger(str, enum.Enum):
    """What set a piece of work going.

    Inferred from timing, not reported by the runtime: a wake with an inbound
    message just before it is the Agent answering someone. Everything else ran
    without a person — a cron, a heartbeat, or the Agent's own follow-up.
    """

    USER = "user"
    BACKGROUND = "background"


class ActivityTotals(PydanticBaseModel):
    calls: int = 0
    wakes: int = 0
    spend: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class PromptTokenDistribution(PydanticBaseModel):
    """How big the prompts were, across the window.

    A high floor with a narrow spread is the fingerprint of a large static
    context resent on every call, which is a different problem from a few long
    conversations — and the averages alone cannot tell them apart.
    """

    avg: float = 0.0
    median: int = 0
    p95: int = 0
    max: int = 0


class ActivityTriggerBreakdown(PydanticBaseModel):
    trigger: ActivityTrigger
    wakes: int = 0
    calls: int = 0
    spend: float = 0.0
    prompt_tokens: int = 0


class ActivityBucketRead(PydanticBaseModel):
    bucket: datetime
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    spend: float = 0.0


class AgentActivitySummaryRead(PydanticBaseModel):
    agent_id: UUID
    period: StatsPeriod | None = None
    from_date: datetime
    to_date: datetime
    granularity: StatsGranularity

    last_call_at: datetime | None = None

    totals: ActivityTotals = Field(default_factory=ActivityTotals)
    prompt_tokens_per_call: PromptTokenDistribution = Field(default_factory=PromptTokenDistribution)
    by_trigger: list[ActivityTriggerBreakdown] = Field(default_factory=list)
    by_bucket: list[ActivityBucketRead] = Field(default_factory=list)

    # Median gap between the starts of consecutive wakes. A steady value is a
    # schedule; None means there were not two wakes to measure between.
    wake_cadence_seconds: int | None = None


class AgentWakeRead(PydanticBaseModel):
    """One burst of model calls, and what it cost."""

    started_at: datetime
    ended_at: datetime
    trigger: ActivityTrigger
    calls: int
    spend: float
    prompt_tokens: int
    completion_tokens: int
    min_prompt_tokens: int
    max_prompt_tokens: int
    models: list[str] = Field(default_factory=list)


class AgentActivityCallRead(PydanticBaseModel):
    """One billed model call, as the Agent's own page shows it."""

    request_id: str
    occurred_at: datetime
    model: str
    status: str
    spend: float
    prompt_tokens: int
    completion_tokens: int
    request_duration_ms: int | None = None


class ActivityFilter(PydanticBaseModel):
    trigger: ActivityTrigger | None = None


def get_activity_filter(trigger: ActivityTrigger | None = Query(default=None)) -> ActivityFilter:
    return ActivityFilter(trigger=trigger)
