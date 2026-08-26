from datetime import datetime
from typing import Any

from pydantic import BaseModel


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
