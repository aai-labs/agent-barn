import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Index, UniqueConstraint
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel as DatabaseBaseModel


class ActorIdentityType(str, enum.Enum):
    MEMBERSHIP = "MEMBERSHIP"
    USER = "USER"
    SYSTEM = "SYSTEM"
    RUNTIME = "RUNTIME"


class SubjectIdentityType(str, enum.Enum):
    AGENT = "AGENT"
    MEMBERSHIP = "MEMBERSHIP"
    ORGANIZATION = "ORGANIZATION"
    TEMPLATE = "TEMPLATE"
    SKILL = "SKILL"
    SYSTEM = "SYSTEM"


class EventDeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class ActorIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: ActorIdentityType
    id: UUID | str
    organization_id: UUID | None = None


class SubjectIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: SubjectIdentityType
    id: UUID | str
    organization_id: UUID | None = None


EventPayload = dict[str, Any]


class DomainEventEnvelope(BaseModel):
    """Typed, tenant-aware internal Domain Event envelope."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_name: str = Field(min_length=1, max_length=255)
    schema_version: int = Field(ge=1)
    occurred_at: datetime
    organization_id: UUID
    actor: ActorIdentity
    subject: SubjectIdentity
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: EventPayload


class OutboxMessage(DatabaseBaseModel, table=True):
    """Immutable PostgreSQL record of a committed Domain Event."""

    __tablename__: str = "event_outbox_message"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_event_outbox_message_event_id"),
        Index("ix_event_outbox_message_organization_occurred", "organization_id", "occurred_at"),
        Index("ix_event_outbox_message_name_version", "event_name", "schema_version"),
    )

    event_id: UUID = SqlField(nullable=False)
    event_name: str = SqlField(nullable=False, max_length=255)
    schema_version: int = SqlField(nullable=False)
    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    actor: dict[str, Any] = SqlField(sa_column=Column(JSONB, nullable=False))
    subject: dict[str, Any] = SqlField(sa_column=Column(JSONB, nullable=False))
    correlation_id: UUID = SqlField(nullable=False)
    causation_id: UUID | None = SqlField(default=None, nullable=True)
    payload: dict[str, Any] = SqlField(sa_column=Column(JSONB, nullable=False))


class EventDelivery(DatabaseBaseModel, table=True):
    """Mutable delivery state for one Domain Event and one Event Handler."""

    __tablename__: str = "event_delivery"
    __table_args__ = (
        UniqueConstraint("event_id", "handler_name", name="uq_event_delivery_event_handler"),
        Index("ix_event_delivery_outbox_message", "outbox_message_id"),
        Index("ix_event_delivery_organization_status", "organization_id", "status"),
    )

    outbox_message_id: UUID = SqlField(foreign_key="event_outbox_message.id", nullable=False, ondelete="CASCADE")
    event_id: UUID = SqlField(nullable=False)
    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    handler_name: str = SqlField(nullable=False, max_length=255)
    status: EventDeliveryStatus = SqlField(
        default=EventDeliveryStatus.PENDING,
        sa_column=Column(sa.Enum(EventDeliveryStatus), nullable=False),
    )
    attempt_count: int = SqlField(default=0, nullable=False, sa_column_kwargs={"server_default": "0"})
    last_error: str | None = SqlField(default=None, nullable=True)
    claimed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
