from datetime import datetime
from typing import Any

from pydantic import BaseModel

from api.domains.conversations.models import ConversationType, MessageDirection


class IngestMessageEvent(BaseModel):
    msg_id: str
    session_key: str
    channel_id: str
    thread_id: str | None = None
    direction: MessageDirection
    conversation_type: ConversationType
    sender_id: str | None = None
    channel_name: str | None = None
    sender_name: str | None = None
    content: str
    occurred_at: datetime


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
    messages: list[IngestMessageEvent] = []
    tool_calls: list[IngestToolCallEvent] = []
    tool_results: list[IngestToolResultEvent] = []
