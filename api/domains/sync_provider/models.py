from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

OPEN_CONNECTION_INDEX = "uq_sync_provider_connection_open"


class SyncProviderCapability(StrEnum):
    LOCATION_PICKER = "location_picker"
    ADMIN_APPROVAL = "admin_approval"


class SyncProviderStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"


class SyncProviderConnection(BaseModel, table=True):
    """An Organization's connection to one storage provider.

    A pending row holds the signing-in person's encrypted delegated token until a location is
    chosen; activation records the location, the Agent Barn folder and the provider's own data,
    and drops the token. Disconnected rows are kept.
    """

    __tablename__: str = "sync_provider_connection"

    __table_args__ = (
        sa.CheckConstraint("schema_version > 0", name="ck_sync_provider_connection_schema_version"),
        sa.Index(
            OPEN_CONNECTION_INDEX,
            "organization_id",
            unique=True,
            postgresql_where=sa.text("status <> 'disconnected'"),
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    provider_key: str = SqlField(nullable=False, max_length=64)
    schema_version: int = SqlField(default=1, sa_column=Column(sa.Integer(), nullable=False, server_default="1"))
    status: SyncProviderStatus = SqlField(sa_column=Column(sa.String(16), nullable=False))
    account_id: str = SqlField(nullable=False, max_length=255)
    connected_by_user_id: UUID | None = SqlField(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    location_id: str | None = SqlField(default=None, nullable=True)
    location_name: str | None = SqlField(default=None, nullable=True)
    location_url: str | None = SqlField(default=None, nullable=True)
    folder_id: str | None = SqlField(default=None, nullable=True)
    folder_web_url: str | None = SqlField(default=None, nullable=True)
    provider_data: dict[str, str] = SqlField(
        default_factory=dict, sa_column=Column(sa.JSON(), nullable=False, server_default="{}")
    )
    credentials_encrypted: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text, repr=False)
    pending_expires_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )
    connected_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))
    disconnected_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )


class SyncProviderDescriptorRead(PydanticBaseModel):
    """What the settings list shows for one provider. Never credentials or provider data."""

    key: str
    display_name: str
    tagline: str
    folder_hint: str
    connect_hint: str | None = None
    location_noun: str | None = None
    schema_version: int
    capabilities: list[SyncProviderCapability]
    available: bool = True
    server_setup_hint: str | None = None


class SyncProviderConnectionRead(PydanticBaseModel):
    """What every Organization Member may see of a connection. Never tokens, the account or provider data."""

    status: SyncProviderStatus
    location_name: str | None = None
    location_url: str | None = None
    folder_web_url: str | None = None
    connected_at: datetime | None = None


class SyncProviderRead(SyncProviderDescriptorRead):
    approval_url: str | None = None
    connection: SyncProviderConnectionRead | None = None
    can_connect: bool
    blocked_reason: str | None = None


class SyncProviderAuthorizeUrlRead(PydanticBaseModel):
    authorize_url: str


class SyncProviderSignInCreate(PydanticBaseModel):
    code: str
    state: str


class SyncLocationRead(PydanticBaseModel):
    id: str
    name: str
    web_url: str


class SyncLocationChoice(PydanticBaseModel):
    location_id: str
