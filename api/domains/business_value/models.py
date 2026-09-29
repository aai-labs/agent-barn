from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import CheckConstraint, Column, Enum, Index, UniqueConstraint
from sqlmodel import Field as SqlField

from api.domains.business_value.classifier import BusinessActionStatus
from api.infrastructure.postgres.models import BaseModel

OUTCOME_TYPE_MAX_LENGTH = 64
TOOL_CALL_ORDINAL_CONSTRAINT = "uq_business_action_tool_call_ordinal"
MAX_HOURLY_RATE_USD = Decimal("10000.00")
MAX_OUTCOME_MINUTES = 1440
VALUE_SETTINGS_ORGANIZATION_CONSTRAINT = "uq_organization_value_settings_organization_id"
VALUE_SETTINGS_HOURLY_RATE_CONSTRAINT = "ck_organization_value_settings_hourly_rate_usd"
OUTCOME_MINUTES_ORGANIZATION_TYPE_CONSTRAINT = "uq_organization_outcome_minutes_organization_id_outcome_type"
OUTCOME_MINUTES_POSITIVE_CONSTRAINT = "ck_organization_outcome_minutes_minutes_saved"


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


class OrganizationValueSettings(BaseModel, table=True):
    __tablename__: str = "organization_value_settings"

    __table_args__ = (
        UniqueConstraint("organization_id", name=VALUE_SETTINGS_ORGANIZATION_CONSTRAINT),
        CheckConstraint(
            "hourly_rate_usd IS NULL OR hourly_rate_usd >= 0",
            name=VALUE_SETTINGS_HOURLY_RATE_CONSTRAINT,
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    hourly_rate_usd: Decimal | None = SqlField(default=None, sa_column=Column(sa.Numeric(12, 2), nullable=True))


class OrganizationOutcomeMinutes(BaseModel, table=True):
    __tablename__: str = "organization_outcome_minutes"

    __table_args__ = (
        UniqueConstraint("organization_id", "outcome_type", name=OUTCOME_MINUTES_ORGANIZATION_TYPE_CONSTRAINT),
        CheckConstraint("minutes_saved > 0", name=OUTCOME_MINUTES_POSITIVE_CONSTRAINT),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    outcome_type: str = SqlField(
        nullable=False,
        sa_type=sa.String(OUTCOME_TYPE_MAX_LENGTH),  # type: ignore
    )
    minutes_saved: int = SqlField(nullable=False)
