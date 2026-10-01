from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column, Enum, Index, UniqueConstraint
from sqlmodel import Field as SqlField

from api.domains.business_value.classifier import BusinessActionStatus
from api.infrastructure.postgres.models import BaseModel

OUTCOME_TYPE_MAX_LENGTH = 64
TOOL_CALL_ORDINAL_CONSTRAINT = "uq_business_action_tool_call_ordinal"


class BusinessAction(BaseModel, table=True):
    __tablename__: str = "business_action"

    __table_args__ = (
        UniqueConstraint("tool_call_id", "ordinal", name=TOOL_CALL_ORDINAL_CONSTRAINT),
        Index("ix_business_action_organization_occurred", "organization_id", "occurred_at"),
        Index("ix_business_action_agent_occurred", "agent_id", "occurred_at"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    tool_call_id: UUID = SqlField(foreign_key="tool_call.id", nullable=False, ondelete="CASCADE")
    ordinal: int = SqlField(nullable=False)
    integration: str = SqlField(nullable=False, sa_type=sa.Text)
    resource: str = SqlField(nullable=False, sa_type=sa.Text)
    verb: str = SqlField(nullable=False, sa_type=sa.Text)
    outcome_type: str | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.String(OUTCOME_TYPE_MAX_LENGTH),  # type: ignore
    )
    is_write: bool | None = SqlField(default=None, nullable=True)
    status: BusinessActionStatus = SqlField(
        sa_column=Column(Enum(BusinessActionStatus), nullable=False),
    )
    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    completed_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
