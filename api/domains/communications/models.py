from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class ConnectionObservedStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class CommunicationPlatform(str, enum.Enum):
    """Stable keys for the communication plugins shipped with Agent Barn."""

    SLACK = "slack"
    TEAMS = "teams"
    TELEGRAM = "telegram"
    DISCORD = "discord"


class PlatformCapability(str, enum.Enum):
    DIRECTORY_DISCOVERY = "directory_discovery"
    APPLICATION_PROVISIONING = "application_provisioning"
    WEBHOOK_INGRESS = "webhook_ingress"
    ATTACHMENTS = "attachments"
    THREADS = "threads"
    MENTIONS = "mentions"
    PROCESSING_FEEDBACK = "processing_feedback"


class ProcessingFeedbackStage(str, enum.Enum):
    ACCEPTED = "accepted"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CredentialUniquenessScope(str, enum.Enum):
    NONE = "none"
    AGENT = "agent"
    ORGANIZATION = "organization"
    GLOBAL = "global"


class CommunicationDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class CommunicationDeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    DEAD_LETTERED = "DEAD_LETTERED"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"


class CommunicationPolicyDisposition(str, enum.Enum):
    """The explicit result of provider payload admission.

    A provider event can be observed without becoming a durable Communication
    Delivery. Keeping that decision typed lets diagnostics explain why an event
    stopped at the policy boundary instead of treating every empty envelope as
    an indistinguishable success.
    """

    ACCEPTED = "accepted"
    BOT_IGNORED = "bot_ignored"
    EVENT_IGNORED = "event_ignored"
    MENTION_REQUIRED = "mention_required"
    USER_DENIED = "user_denied"
    CHANNEL_DENIED = "channel_denied"
    MALFORMED_PAYLOAD = "malformed_payload"


class CommunicationErrorCategory(str, enum.Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class CommunicationErrorDetails(PydanticBaseModel):
    """Structured, content-free diagnostics safe to show to an Agent user."""

    model_config = ConfigDict(extra="forbid")

    category: CommunicationErrorCategory
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_code: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]{1,100}$",
    )
    retryable: bool
    retry_after_seconds: int | None = Field(default=None, ge=0, le=86_400)
    request_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]{1,128}$",
    )


class CommunicationJournalStage(str, enum.Enum):
    PROVIDER_OBSERVED = "provider_observed"
    POLICY_ADMITTED = "policy_admitted"
    POLICY_REJECTED = "policy_rejected"
    QUEUED = "queued"
    AGENT_CLAIMED = "agent_claimed"
    MODEL_COMPLETED = "model_completed"
    REPLY_QUEUED = "reply_queued"
    PROVIDER_DELIVERY_ATTEMPTED = "provider_delivery_attempted"
    PROVIDER_DELIVERED = "provider_delivered"
    CONNECTION_CONNECTING = "connection_connecting"
    CONNECTION_CONNECTED = "connection_connected"
    CONNECTION_DEGRADED = "connection_degraded"
    CONNECTION_ERROR = "connection_error"
    RECONNECT_REQUESTED = "reconnect_requested"
    RETRY_REQUESTED = "retry_requested"
    DEAD_LETTERED = "dead_lettered"
    RECOVERED = "recovered"


class CommunicationConnection(BaseModel, table=True):
    __tablename__: str = "communication_connection"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_communication_connection_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("schema_version > 0", name="ck_communication_connection_schema_version"),
        sa.CheckConstraint("revision > 0", name="ck_communication_connection_revision"),
        sa.UniqueConstraint("id", "organization_id", name="uq_communication_connection_id_organization"),
        sa.Index("ix_communication_connection_agent", "agent_id"),
        sa.Index("ix_communication_connection_organization", "organization_id"),
        sa.Index("ix_communication_connection_platform", "platform_key"),
        sa.Index(
            "uq_communication_connection_active_name",
            "agent_id",
            sa.func.lower(sa.column("display_name")),
            unique=True,
            postgresql_where=sa.text("retired_at IS NULL"),
        ),
        sa.UniqueConstraint(
            "platform_key",
            "credential_scope_key",
            "credential_fingerprint",
            name="uq_communication_connection_credential",
        ),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    platform_key: str = SqlField(nullable=False, max_length=64)
    display_name: str = SqlField(nullable=False, max_length=255)
    enabled: bool = SqlField(
        default=True,
        sa_column=Column(sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    schema_version: int = SqlField(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    settings: dict[str, Any] = SqlField(
        default_factory=dict,
        sa_column=Column(sa.JSON(), nullable=False, server_default="{}"),
    )
    credentials_encrypted: str = SqlField(nullable=False, sa_type=sa.Text)
    driver_key_encrypted: str = SqlField(nullable=False, sa_type=sa.Text)
    external_identity: str | None = SqlField(default=None, nullable=True, max_length=512)
    credential_fingerprint: str | None = SqlField(default=None, nullable=True, max_length=128)
    credential_scope_key: str | None = SqlField(default=None, nullable=True, max_length=128)
    observed_status: ConnectionObservedStatus | None = SqlField(
        default=None,
        sa_column=Column(sa.Enum(ConnectionObservedStatus), nullable=True),
    )
    last_health_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    last_error_code: str | None = SqlField(default=None, nullable=True, max_length=100)
    last_error_message: str | None = SqlField(default=None, nullable=True, max_length=500)
    last_error_details: dict[str, Any] | None = SqlField(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    ingress_lease_owner: str | None = SqlField(default=None, nullable=True, max_length=64)
    ingress_lease_expires_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    revision: int = SqlField(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    retired_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )


class CommunicationDelivery(BaseModel, table=True):
    __tablename__: str = "communication_delivery"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["connection_id", "organization_id"],
            ["communication_connection.id", "communication_connection.organization_id"],
            name="fk_communication_delivery_connection_organization",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "direction",
            "idempotency_key",
            name="uq_communication_delivery_idempotency",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_communication_delivery_attempt_count"),
        sa.Index("ix_communication_delivery_connection_status", "connection_id", "status"),
        sa.Index("ix_communication_delivery_status_available", "status", "available_at"),
        sa.Index("ix_communication_delivery_ordering", "ordering_key", "created_at"),
        sa.Index("ix_communication_delivery_agent", "agent_id"),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    connection_id: UUID = SqlField(nullable=False)
    message_id: UUID = SqlField(
        foreign_key="agent_chat_message.id",
        nullable=False,
        ondelete="RESTRICT",
    )
    direction: CommunicationDirection = SqlField(sa_column=Column(sa.String(16), nullable=False))
    status: CommunicationDeliveryStatus = SqlField(
        default=CommunicationDeliveryStatus.PENDING,
        sa_column=Column(sa.String(32), nullable=False, server_default="PENDING"),
    )
    idempotency_key: str = SqlField(nullable=False, max_length=512)
    ordering_key: str = SqlField(nullable=False, max_length=1024)
    attempt_count: int = SqlField(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    available_at: datetime = SqlField(nullable=False, sa_type=sa.DateTime(timezone=True))  # type: ignore
    claimed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
    lease_expires_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    completed_at: datetime | None = SqlField(default=None, nullable=True, sa_type=sa.DateTime(timezone=True))  # type: ignore
    provider_message_id: str | None = SqlField(default=None, nullable=True, max_length=512)
    last_error_code: str | None = SqlField(default=None, nullable=True, max_length=100)
    last_error_message: str | None = SqlField(default=None, nullable=True, max_length=500)
    envelope: dict[str, Any] = SqlField(sa_column=Column(JSONB, nullable=False))


class CommunicationJournalEntry(BaseModel, table=True):
    """Append-only, content-free operational history for one Connection.

    This table intentionally stores only lifecycle facts and safe summaries.
    Provider payloads, message text, credentials, and sender identity do not
    belong in diagnostics history.
    """

    __tablename__: str = "communication_operation_journal"
    __table_args__ = (
        sa.CheckConstraint("attempt_number >= 0", name="ck_communication_journal_attempt_number"),
        sa.Index(
            "ix_communication_journal_connection_occurred",
            "connection_id",
            "occurred_at",
        ),
        sa.Index(
            "ix_communication_journal_delivery_occurred",
            "delivery_id",
            "occurred_at",
        ),
        sa.Index(
            "ix_communication_journal_agent_occurred",
            "agent_id",
            "occurred_at",
        ),
        sa.Index(
            "ix_communication_journal_occurred",
            "occurred_at",
        ),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    connection_id: UUID = SqlField(nullable=False)
    delivery_id: UUID | None = SqlField(default=None, nullable=True)
    occurred_at: datetime = SqlField(
        sa_type=sa.DateTime(timezone=True),  # type: ignore
        nullable=False,
    )
    stage: CommunicationJournalStage = SqlField(
        sa_column=Column(sa.String(64), nullable=False),
    )
    disposition: CommunicationPolicyDisposition | None = SqlField(
        default=None,
        sa_column=Column(sa.String(32), nullable=True),
    )
    attempt_number: int = SqlField(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    duration_ms: float | None = SqlField(default=None, nullable=True)
    error_code: str | None = SqlField(default=None, nullable=True, max_length=100)
    error_summary: str | None = SqlField(default=None, nullable=True, max_length=500)
    error_details: dict[str, Any] | None = SqlField(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class CommunicationAttachment(PydanticBaseModel):
    id: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=255)
    filename: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)


class ConversationLocation(PydanticBaseModel):
    id: str = Field(min_length=1, max_length=512)
    type: str = Field(pattern="^(CHANNEL|DM)$")
    display_name: str | None = Field(default=None, max_length=255)
    thread_id: str | None = Field(default=None, max_length=512)


class CommunicationSender(PydanticBaseModel):
    id: str | None = Field(default=None, max_length=512)
    display_name: str | None = Field(default=None, max_length=255)


class NormalizedCommunicationEnvelope(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    provider_message_id: str = Field(min_length=1, max_length=512)
    occurred_at: datetime
    location: ConversationLocation
    sender: CommunicationSender = Field(default_factory=CommunicationSender)
    text: str = ""
    mentions: list[str] = Field(default_factory=list)
    attachments: list[CommunicationAttachment] = Field(default_factory=list)
    reply_to_provider_message_id: str | None = Field(default=None, max_length=512)
    provider_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class AcceptedCommunicationRead(PydanticBaseModel):
    message_id: UUID
    delivery_id: UUID
    status: CommunicationDeliveryStatus
    duplicate: bool = False


class CommunicationJournalEntryRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_id: UUID
    delivery_id: UUID | None
    occurred_at: datetime
    stage: CommunicationJournalStage
    disposition: CommunicationPolicyDisposition | None
    attempt_number: int
    duration_ms: float | None
    error_code: str | None
    error_summary: str | None
    error_details: CommunicationErrorDetails | None = None
    direction: CommunicationDirection | None = None
    delivery_status: CommunicationDeliveryStatus | None = None
    queue_wait_ms: float | None = None
    processing_ms: float | None = None
    next_retry_at: datetime | None = None


class CommunicationPipelineCounts(PydanticBaseModel):
    provider_observed: int = 0
    policy_admitted: int = 0
    queued: int = 0
    agent_claimed: int = 0
    model_completed: int = 0
    reply_queued: int = 0
    provider_delivered: int = 0
    dead_lettered: int = 0


class CommunicationDeliveryCounts(PydanticBaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    succeeded: int = 0
    dead_lettered: int = 0
    cancelled: int = 0
    unavailable: int = 0


class CommunicationLatencyRead(PydanticBaseModel):
    sample_count: int = 0
    average_ms: float | None = None
    p50_ms: float | None = None
    latest_ms: float | None = None


class CommunicationFailureRead(PydanticBaseModel):
    occurred_at: datetime
    stage: CommunicationJournalStage
    delivery_id: UUID | None
    error_code: str | None
    error_summary: str | None
    error_details: CommunicationErrorDetails | None = None


class CommunicationTransitionRead(PydanticBaseModel):
    occurred_at: datetime
    stage: CommunicationJournalStage
    delivery_id: UUID | None
    disposition: CommunicationPolicyDisposition | None
    attempt_number: int
    duration_ms: float | None


class CommunicationConnectionStateRead(PydanticBaseModel):
    """One contiguous provider state interval inside a diagnostics window."""

    status: ConnectionObservedStatus
    started_at: datetime
    ended_at: datetime | None
    next_status: ConnectionObservedStatus | None
    duration_ms: float
    reconnect_count: int = 0
    error_code: str | None = None
    error_summary: str | None = None


class CommunicationConnectionIncidentOutcome(str, enum.Enum):
    RECONNECTED = "RECONNECTED"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"


class CommunicationConnectionIncidentRead(PydanticBaseModel):
    """One connection attempt projected from contiguous provider states."""

    started_at: datetime
    outcome: CommunicationConnectionIncidentOutcome
    connect_time_ms: float | None
    outage_ms: float | None
    cause_code: str | None = None
    cause_summary: str | None = None
    reconnect_count: int = 0


class CommunicationDiagnosticsRead(PydanticBaseModel):
    connection: CommunicationConnectionRead
    provider_connectivity: ConnectionObservedStatus | None
    end_to_end_health: str
    pipeline: CommunicationPipelineCounts
    delivery_counts: CommunicationDeliveryCounts
    queue_depth: int
    oldest_queued_age_seconds: float | None
    oldest_pending_delivery_age_seconds: float | None
    latency: CommunicationLatencyRead
    last_successful_connection_at: datetime | None
    current_error_age_seconds: float | None
    consecutive_failure_count: int
    delivery_success_rate: float | None
    recent_failures: list[CommunicationFailureRead]
    latest_transitions: list[CommunicationTransitionRead]
    connection_history: list[CommunicationConnectionStateRead]
    connection_incidents: list[CommunicationConnectionIncidentRead]
    reconnect_count: int
    median_connect_time_ms: float | None
    longest_outage_ms: float | None
    window_start: datetime
    window_end: datetime


class CommunicationReconnectRead(PydanticBaseModel):
    connection: CommunicationConnectionRead
    requested_at: datetime


class CommunicationRetryRead(PydanticBaseModel):
    delivery_id: UUID
    status: CommunicationDeliveryStatus
    attempt_count: int
    requested_at: datetime


class RuntimeDeliveryRead(PydanticBaseModel):
    delivery_id: UUID
    message_id: UUID
    connection_id: UUID
    attempt_count: int
    envelope: NormalizedCommunicationEnvelope


class RuntimeDeliveryResult(PydanticBaseModel):
    succeeded: bool
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)


class RuntimeReplyCreate(PydanticBaseModel):
    idempotency_key: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=100_000)
    attachments: list[CommunicationAttachment] = Field(default_factory=list)


class OutboundCommunicationEnvelope(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    source_delivery_id: UUID
    location: ConversationLocation
    text: str = Field(min_length=1, max_length=100_000)
    attachments: list[CommunicationAttachment] = Field(default_factory=list)
    reply_to_provider_message_id: str | None = Field(default=None, max_length=512)
    provider_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PlatformDescriptorRead(PydanticBaseModel):
    key: str
    display_name: str
    schema_version: int
    capabilities: list[PlatformCapability]
    settings_schema: dict[str, Any]
    credentials_schema: dict[str, Any]
    setup_hint: str | None = None
    post_setup_hint: str | None = None


class CommunicationDirectoryEntryRead(PydanticBaseModel):
    """One safe-to-display provider directory item used to configure a Connection."""

    id: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=255)
    detail: str | None = Field(default=None, max_length=255)


class CommunicationDirectoryPreview(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_key: str = Field(min_length=1, max_length=64)
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any]


class CommunicationDirectoryPreviewRead(PydanticBaseModel):
    channels: list[CommunicationDirectoryEntryRead] = Field(default_factory=list)
    users: list[CommunicationDirectoryEntryRead] = Field(default_factory=list)


class CommunicationConnectionCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any]


class CommunicationConnectionUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    settings: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> CommunicationConnectionUpdate:
        if not self.model_fields_set.difference({"revision"}):
            raise ValueError("At least one connection field must be updated")
        return self


class CommunicationConnectionRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    platform_key: str
    display_name: str
    enabled: bool
    schema_version: int
    settings: dict[str, Any]
    external_identity: str | None
    observed_status: ConnectionObservedStatus | None
    last_health_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    last_error_details: CommunicationErrorDetails | None = None
    webhook_url: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
