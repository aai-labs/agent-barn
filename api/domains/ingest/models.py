from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IngestToolCallEvent(BaseModel):
    external_id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    occurred_at: datetime


class IngestToolResultEvent(BaseModel):
    external_id: str
    result: Any | None = None
    is_error: bool = False
    completed_at: datetime


class IngestBatchRequest(BaseModel):
    tool_calls: list[IngestToolCallEvent] = []
    tool_results: list[IngestToolResultEvent] = []


class IngestCommunicationEvent(BaseModel):
    """A content-free native gateway Journal stage reported by the runtime observer."""

    stage: str = Field(max_length=64)
    platform: str = Field(max_length=32)
    correlation_id: str | None = Field(default=None, max_length=512)
    occurred_at: datetime
    error_code: str | None = Field(default=None, max_length=100)


class IngestCommunicationEventBatch(BaseModel):
    events: list[IngestCommunicationEvent] = Field(default_factory=list, max_length=500)
