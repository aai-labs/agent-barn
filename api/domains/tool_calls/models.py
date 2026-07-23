import enum
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Enum, Field as SqlField, Index, UniqueConstraint

from api.infrastructure.postgres.models import BaseModel


class ToolCallStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class ToolCall(BaseModel, table=True):
    __tablename__: str = "tool_call"

    __table_args__ = (
        Index("ix_tool_call_agent_occurred", "agent_id", "occurred_at"),
        Index("ix_tool_call_agent_tool", "agent_id", "tool_name"),
        UniqueConstraint("agent_id", "external_id", name="uq_tool_call_agent_external"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    session_id: str = SqlField(nullable=False)
    external_id: str = SqlField(nullable=False)
    tool_name: str = SqlField(nullable=False)
    arguments: dict[str, Any] = SqlField(
        sa_column=Column(JSONB, nullable=False),
    )
    result: Any | None = SqlField(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    status: ToolCallStatus = SqlField(
        sa_column=Column(Enum(ToolCallStatus), nullable=False),
    )
    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    completed_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    duration_ms: int | None = SqlField(default=None, nullable=True)


class ToolCallRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: Any | None
    status: ToolCallStatus
    occurred_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class ToolCallFilter(PydanticBaseModel):
    tool_name: str | None = None
    status: ToolCallStatus | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None


def get_tool_call_filter(
    tool_name: str | None = Query(default=None),
    status: ToolCallStatus | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
) -> ToolCallFilter:
    return ToolCallFilter(
        tool_name=tool_name,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )
