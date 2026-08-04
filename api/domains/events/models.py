import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import Query
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
    USER = "USER"


class EventScope(str, enum.Enum):
    ORGANIZATION = "ORGANIZATION"
    PLATFORM = "PLATFORM"


class EventDeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    ENQUEUED = "ENQUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    DEAD_LETTERED = "DEAD_LETTERED"


class EventDeliveryDeadLetterReason(str, enum.Enum):
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    TERMINAL_HANDLER_ERROR = "TERMINAL_HANDLER_ERROR"
    UNKNOWN_HANDLER = "UNKNOWN_HANDLER"
    UNSUPPORTED_EVENT = "UNSUPPORTED_EVENT"
    INVALID_DELIVERY = "INVALID_DELIVERY"


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
    event_scope: EventScope
    organization_id: UUID | None
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
        Index("ix_event_outbox_message_scope_occurred", "event_scope", "occurred_at"),
        Index("ix_event_outbox_message_name_version", "event_name", "schema_version"),
        sa.CheckConstraint(
            "(event_scope = 'ORGANIZATION' AND organization_id IS NOT NULL) "
            "OR (event_scope = 'PLATFORM' AND organization_id IS NULL)",
            name="ck_event_outbox_message_scope_organization",
        ),
    )

    event_id: UUID = SqlField(nullable=False)
    event_name: str = SqlField(nullable=False, max_length=255)
    schema_version: int = SqlField(nullable=False)
    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    event_scope: EventScope = SqlField(
        sa_column=Column(sa.String(32), nullable=False),
    )
    organization_id: UUID | None = SqlField(
        default=None,
        nullable=True,
    )
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
        sa.CheckConstraint(
            "(status = 'DEAD_LETTERED' AND dead_letter_reason IS NOT NULL) "
            "OR (status <> 'DEAD_LETTERED' AND dead_letter_reason IS NULL)",
            name="ck_event_delivery_dead_letter_reason_matches_status",
        ),
        Index("ix_event_delivery_outbox_message", "outbox_message_id"),
        Index("ix_event_delivery_organization_status", "organization_id", "status"),
        Index("ix_event_delivery_scope_status", "event_scope", "status"),
        sa.CheckConstraint(
            "(event_scope = 'ORGANIZATION' AND organization_id IS NOT NULL) "
            "OR (event_scope = 'PLATFORM' AND organization_id IS NULL)",
            name="ck_event_delivery_scope_organization",
        ),
        Index("ix_event_delivery_status_created_at", "status", "created_at"),
        Index("ix_event_delivery_status_enqueued_at", "status", "enqueued_at"),
        Index("ix_event_delivery_status_claimed_at", "status", "claimed_at"),
        Index("ix_event_delivery_created_at_id", "created_at", "id"),
        Index("ix_event_delivery_organization_created_at", "organization_id", "created_at"),
    )

    outbox_message_id: UUID = SqlField(foreign_key="event_outbox_message.id", nullable=False, ondelete="CASCADE")
    event_id: UUID = SqlField(nullable=False)
    event_scope: EventScope = SqlField(
        sa_column=Column(sa.String(32), nullable=False),
    )
    organization_id: UUID | None = SqlField(
        default=None,
        nullable=True,
    )
    handler_name: str = SqlField(nullable=False, max_length=255)
    status: EventDeliveryStatus = SqlField(
        default=EventDeliveryStatus.PENDING,
        sa_column=Column(sa.Enum(EventDeliveryStatus), nullable=False),
    )
    attempt_count: int = SqlField(default=0, nullable=False, sa_column_kwargs={"server_default": "0"})
    last_error: str | None = SqlField(default=None, nullable=True)
    dead_letter_reason: EventDeliveryDeadLetterReason | None = SqlField(
        default=None,
        sa_column=Column(sa.Enum(EventDeliveryDeadLetterReason), nullable=True),
    )
    enqueued_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
    claimed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
    completed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore


class EventDeliverySortDirection(str, enum.Enum):
    NEWEST_FIRST = "NEWEST_FIRST"
    OLDEST_FIRST = "OLDEST_FIRST"


class EventDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_name: str
    schema_version: int
    handler_name: str
    organization_id: UUID | None
    organization_name: str
    status: EventDeliveryStatus
    attempt_count: int
    dead_letter_reason: EventDeliveryDeadLetterReason | None = None
    last_error: str | None = None
    created_at: datetime
    enqueued_at: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    status_since: datetime | None = None
    observed_at: datetime


class EventDeliveryFilter(BaseModel):
    search: str | None = None
    status: EventDeliveryStatus | None = None
    organization_id: UUID | None = None
    event_name: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: EventDeliverySortDirection = EventDeliverySortDirection.NEWEST_FIRST


def get_event_delivery_filter(
    search: str | None = Query(default=None),
    status: EventDeliveryStatus | None = Query(default=None),
    organization_id: UUID | None = Query(default=None),
    event_name: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    sort: EventDeliverySortDirection = Query(default=EventDeliverySortDirection.NEWEST_FIRST),
) -> EventDeliveryFilter:
    return EventDeliveryFilter(
        search=search,
        status=status,
        organization_id=organization_id,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
    )


class EventDeliveryStatusCounts(BaseModel):
    pending: int
    enqueued: int
    processing: int
    succeeded: int
    dead_lettered: int


class EventDeliveryActiveStateStats(BaseModel):
    count: int
    oldest_age_seconds: float | None = None
    stale_threshold_seconds: int
    stale_count: int
    unknown_age_count: int


class EventDeliverySummaryRead(BaseModel):
    observed_at: datetime
    total_count: int
    status_counts: EventDeliveryStatusCounts
    pending: EventDeliveryActiveStateStats
    enqueued: EventDeliveryActiveStateStats
    processing: EventDeliveryActiveStateStats


class SupportedEventTypeRead(BaseModel):
    event_name: str
    schema_versions: list[int]
