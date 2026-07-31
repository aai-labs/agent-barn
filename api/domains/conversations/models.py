import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlmodel import Column, Enum
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class MessageDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class ConversationType(str, enum.Enum):
    CHANNEL = "CHANNEL"
    DM = "DM"


class AgentChatMessage(BaseModel, table=True):
    __tablename__: str = "agent_chat_message"

    __table_args__ = (
        sa.UniqueConstraint("agent_id", "openclaw_msg_id", name="uq_agent_chat_message_agent_msg"),
        sa.Index("ix_agent_chat_message_agent_channel", "agent_id", "channel_id"),
        sa.Index("ix_agent_chat_message_agent_session", "agent_id", "session_key"),
    )

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    openclaw_msg_id: str = SqlField(nullable=False)
    session_key: str = SqlField(nullable=False)
    channel_id: str = SqlField(nullable=False)
    thread_id: str | None = SqlField(default=None, nullable=True)
    direction: MessageDirection = SqlField(sa_column=Column(Enum(MessageDirection), nullable=False))
    conversation_type: ConversationType = SqlField(
        default=ConversationType.CHANNEL,
        sa_column=Column(Enum(ConversationType), nullable=False, server_default="CHANNEL"),
    )
    sender_id: str | None = SqlField(default=None, nullable=True)
    sender_name: str | None = SqlField(default=None, nullable=True)
    channel_name: str | None = SqlField(default=None, nullable=True)
    content: str = SqlField(nullable=False)
    occurred_at: datetime = SqlField(sa_column=Column(sa.DateTime(timezone=True), nullable=False))


class ConversationMessageRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: MessageDirection
    thread_id: str | None
    sender_id: str | None
    sender_name: str | None
    content: str
    occurred_at: datetime


class ConversationChannelRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_id: str
    channel_name: str | None
    conversation_type: ConversationType = ConversationType.CHANNEL


class ConversationsFilter(PydanticBaseModel):
    from_date: datetime | None = None
    to_date: datetime | None = None


class ConversationsCursor(PydanticBaseModel):
    before_occurred_at: datetime | None = None
    before_id: UUID | None = None


class ConversationMessagesPage(PydanticBaseModel):
    messages: list[ConversationMessageRead]
    has_more: bool
    next_cursor: ConversationsCursor | None


class ConversationThreadRead(PydanticBaseModel):
    root: ConversationMessageRead
    replies: list[ConversationMessageRead]


class ConversationThreadsPage(PydanticBaseModel):
    threads: list[ConversationThreadRead]
    has_more: bool
    next_cursor: ConversationsCursor | None
