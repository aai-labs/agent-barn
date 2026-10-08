from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.domains.conversations.models import ConversationType, MessageDirection


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


class IngestNativeTranscriptMessage(BaseModel):
    """A dashboard transcript message reported by a native runtime observer."""

    platform: str = Field(max_length=32)
    provider_message_id: str = Field(min_length=1, max_length=512)
    session_key: str = Field(min_length=1, max_length=512)
    channel_id: str = Field(min_length=1, max_length=512)
    thread_id: str | None = Field(default=None, max_length=512)
    direction: MessageDirection
    conversation_type: ConversationType
    sender_id: str | None = Field(default=None, max_length=512)
    sender_name: str | None = Field(default=None, max_length=512)
    channel_name: str | None = Field(default=None, max_length=512)
    content: str = Field(min_length=1, max_length=100_000)
    occurred_at: datetime


class IngestCommunicationEventBatch(BaseModel):
    events: list[IngestCommunicationEvent] = Field(default_factory=list, max_length=500)
    messages: list[IngestNativeTranscriptMessage] = Field(default_factory=list, max_length=500)
