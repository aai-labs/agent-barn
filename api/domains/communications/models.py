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
    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"


class PlatformCapability(str, enum.Enum):
    DIRECTORY_DISCOVERY = "directory_discovery"
    APPLICATION_PROVISIONING = "application_provisioning"
    WEBHOOK_INGRESS = "webhook_ingress"
    MANAGED_ADDRESS = "managed_address"
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
    webhook_url: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
