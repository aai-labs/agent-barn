from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.conversations.models import MessageDirection
from api.infrastructure.postgres.models import BaseModel

MAIN_THREAD_ID = "main"


class WebChatThread(BaseModel, table=True):
    """Metadata overlay for a web chat thread — a thread otherwise only exists
    implicitly as a thread_id value on agent_chat_message rows. Scoped by
    channel_id (the dashboard user) in addition to connection_id: multiple
    users of the same Agent's web Connection all use the literal thread_id
    "main" for their own default thread, so channel_id is required to avoid
    one user's rename/delete leaking onto another user's thread of the same
    name.
    """

    __tablename__: str = "web_chat_thread"
    __table_args__ = (
        sa.UniqueConstraint(
            "connection_id",
            "channel_id",
            "thread_id",
            name="uq_web_chat_thread_connection_channel_thread",
        ),
        sa.Index("ix_web_chat_thread_connection_channel", "connection_id", "channel_id"),
    )

    connection_id: UUID = SqlField(
        foreign_key="communication_connection.id",
        nullable=False,
        ondelete="CASCADE",
    )
    channel_id: str = SqlField(nullable=False, max_length=512)
    thread_id: str = SqlField(nullable=False, max_length=128)
    display_name: str | None = SqlField(default=None, nullable=True, max_length=255)
    deleted_at: datetime | None = SqlField(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )


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
    title: str
    last_occurred_at: datetime | None
    last_content: str | None


class WebChatThreadRename(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
