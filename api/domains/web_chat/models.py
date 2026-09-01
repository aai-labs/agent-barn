from datetime import datetime
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from api.domains.conversations.models import MessageDirection

MAIN_THREAD_ID = "main"


class WebChatMessageRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: MessageDirection
    content: str
    occurred_at: datetime


class WebChatMessageCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
    thread_id: str = Field(default=MAIN_THREAD_ID, min_length=1, max_length=128)


class WebChatThreadRead(PydanticBaseModel):
    thread_id: str
    last_occurred_at: datetime
    last_content: str
