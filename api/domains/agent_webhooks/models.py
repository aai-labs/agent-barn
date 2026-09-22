from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class WebhookInvocationStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    SUBMITTED = "SUBMITTED"
    DISPATCH_FAILED = "DISPATCH_FAILED"


class WebhookDeliveryPlatform(str, enum.Enum):
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    TEAMS = "teams"


class WebhookDeliveryPlatformRead(PydanticBaseModel):
    key: WebhookDeliveryPlatform
    display_name: str


class AgentWebhook(BaseModel, table=True):
    __tablename__: str = "agent_webhook"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_webhook_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_webhook_id_organization"),
        sa.Index("ix_agent_webhook_agent", "agent_id"),
        sa.Index("ix_agent_webhook_organization", "organization_id"),
        sa.Index(
            "uq_agent_webhook_active_name",
            "agent_id",
            sa.func.lower(sa.column("display_name")),
            unique=True,
            postgresql_where=sa.text("retired_at IS NULL"),
        ),
        sa.CheckConstraint("revision > 0", name="ck_agent_webhook_revision"),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    display_name: str = SqlField(nullable=False, max_length=255)
    delivery_platform: WebhookDeliveryPlatform = SqlField(
        sa_column=Column(sa.String(16), nullable=False),
    )
    enabled: bool = SqlField(
        default=True,
        sa_column=Column(sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    signing_secret_encrypted: str = SqlField(nullable=False, sa_type=sa.Text)
    revision: int = SqlField(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    retired_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )


class WebhookInvocation(BaseModel, table=True):
    __tablename__: str = "webhook_invocation"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["webhook_id", "organization_id"],
            ["agent_webhook.id", "agent_webhook.organization_id"],
            name="fk_webhook_invocation_webhook_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_webhook_invocation_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("webhook_id", "external_event_id", name="uq_webhook_invocation_external_event"),
        sa.Index("ix_webhook_invocation_webhook_created", "webhook_id", "created_at"),
        sa.Index("ix_webhook_invocation_agent_status", "agent_id", "status"),
        sa.CheckConstraint("dispatch_attempt_count >= 0", name="ck_webhook_invocation_dispatch_attempt_count"),
        sa.CheckConstraint("dispatch_generation > 0", name="ck_webhook_invocation_dispatch_generation"),
    )

    organization_id: UUID = SqlField(nullable=False)
    agent_id: UUID = SqlField(nullable=False)
    webhook_id: UUID = SqlField(nullable=False)
    external_event_id: str | None = SqlField(default=None, nullable=True, max_length=512)
    prompt: str = SqlField(nullable=False, sa_type=sa.Text)
    status: WebhookInvocationStatus = SqlField(
        default=WebhookInvocationStatus.RECEIVED,
        sa_column=Column(sa.String(16), nullable=False, server_default="RECEIVED"),
    )
    dispatch_attempt_count: int = SqlField(
        default=0,
        sa_column=Column(sa.Integer(), nullable=False, server_default="0"),
    )
    dispatch_generation: int = SqlField(
        default=1,
        sa_column=Column(sa.Integer(), nullable=False, server_default="1"),
    )
    submitted_at: datetime | None = SqlField(
        default=None,
        nullable=True,
        sa_type=sa.DateTime(timezone=True),  # type: ignore
    )
    native_job_id: str | None = SqlField(default=None, nullable=True, max_length=255)
    last_error_code: str | None = SqlField(default=None, nullable=True, max_length=100)
    last_error_message: str | None = SqlField(default=None, nullable=True, max_length=500)


class AgentWebhookCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
    delivery_platform: WebhookDeliveryPlatform
    enabled: bool = True

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank")
        if "\x00" in value:
            raise ValueError("display_name must not contain NUL characters")
        return value.strip()


class AgentWebhookUpdate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    delivery_platform: WebhookDeliveryPlatform | None = None
    enabled: bool | None = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("display_name must not be blank")
        if value is not None and "\x00" in value:
            raise ValueError("display_name must not contain NUL characters")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> AgentWebhookUpdate:
        if not self.model_fields_set.difference({"revision"}):
            raise ValueError("At least one webhook field must be updated")
        return self


class AgentWebhookRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    display_name: str
    delivery_platform: WebhookDeliveryPlatform
    enabled: bool
    revision: int
    webhook_url: str | None
    signing_secret: str | None = None
    created_at: datetime
    updated_at: datetime


class WebhookInvocationCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None = Field(default=None, min_length=1, max_length=512)
    prompt: str = Field(min_length=1, max_length=5_000)

    @field_validator("event_id", "prompt")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("value must not be blank")
        if "\x00" in value:
            raise ValueError("value must not contain NUL characters")
        return value.strip()


class WebhookInvocationAccepted(PydanticBaseModel):
    invocation_id: UUID
    status: WebhookInvocationStatus
    duplicate: bool = False


class WebhookInvocationRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_id: UUID
    external_event_id: str | None
    prompt: str
    status: WebhookInvocationStatus
    dispatch_attempt_count: int
    dispatch_generation: int
    submitted_at: datetime | None
    native_job_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
