from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class OneDriveSyncStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"


class OneDriveSyncConnection(BaseModel, table=True):
    """An Organization's connection to one SharePoint site through the platform Microsoft app.

    A pending row holds the signing-in administrator's encrypted delegated token until a site
    is chosen; activation records the site grant and the Agent Barn folder and drops the token.
    Disconnected rows are kept, so at most one row per Organization is open at a time.
    """

    __tablename__: str = "onedrive_sync_connection"

    __table_args__ = (
        sa.Index(
            "uq_onedrive_sync_connection_open",
            "organization_id",
            unique=True,
            postgresql_where=sa.text("status <> 'disconnected'"),
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    status: OneDriveSyncStatus = SqlField(sa_column=Column(sa.String(16), nullable=False))
    tenant_id: str = SqlField(nullable=False, max_length=64)
    connected_by_user_id: UUID | None = SqlField(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    site_id: str | None = SqlField(default=None, nullable=True)
    site_name: str | None = SqlField(default=None, nullable=True)
    site_url: str | None = SqlField(default=None, nullable=True)
    folder_item_id: str | None = SqlField(default=None, nullable=True)
    folder_web_url: str | None = SqlField(default=None, nullable=True)
    permission_id: str | None = SqlField(default=None, nullable=True)
    pending_access_token: str | None = SqlField(default=None, nullable=True, repr=False)
    pending_expires_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )
    connected_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))
    disconnected_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )
