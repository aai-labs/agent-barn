from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field
from sqlalchemy import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

MAX_MANIFEST_ENTRIES = 10_000
MAX_PATH_LENGTH = 1024
FOLDER_NAME_INDEX = "uq_sync_agent_folder_connection_name"
FOLDER_AGENT_INDEX = "uq_sync_agent_folder_connection_agent"
FILE_PATH_INDEX = "uq_sync_file_folder_path"
FILE_ITEM_INDEX = "uq_sync_file_folder_item"


class SyncFolderStatus(StrEnum):
    ACTIVE = "active"
    STOPPED = "stopped"
    DISABLED = "disabled"


class SyncPendingAction(StrEnum):
    DOWNLOAD = "download"
    REUPLOAD = "reupload"


class SyncActivityKind(StrEnum):
    EDIT_UNDONE = "edit_undone"
    RESTORED = "restored"
    RENAMED_BACK = "renamed_back"
    MOVED_NOT_SYNCED = "moved_not_synced"
    CONFLICT_AGENT_WON = "conflict_agent_won"
    DELETED_BY_AGENT = "deleted_by_agent"
    FOLDER_RESTORED = "folder_restored"
    SKIPPED_TOO_LARGE = "skipped_too_large"
    SKIPPED_NO_SPACE = "skipped_no_space"
    SKIPPED_NAME = "skipped_name"


class SyncAgentFolder(BaseModel, table=True):
    """One Agent's folder inside the connection's "Agent Barn" folder.

    `folder_item_id` is empty until the folder exists at the provider. A deleted Agent's folder is
    `stopped` and stays at the provider; `disabled` is sync turned off for a live Agent.
    """

    __tablename__: str = "sync_agent_folder"

    __table_args__ = (
        sa.Index(FOLDER_AGENT_INDEX, "connection_id", "agent_id", unique=True),
        sa.Index(FOLDER_NAME_INDEX, "connection_id", sa.text("lower(folder_name)"), unique=True),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    connection_id: UUID = SqlField(foreign_key="sync_provider_connection.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    folder_name: str = SqlField(nullable=False, max_length=255)
    folder_item_id: str | None = SqlField(default=None, nullable=True)
    folder_web_url: str | None = SqlField(default=None, nullable=True)
    folder_path: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text)
    status: SyncFolderStatus = SqlField(sa_column=Column(sa.String(16), nullable=False))
    last_contact_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )


class SyncFile(BaseModel, table=True):
    """One synced path of an Agent's folder.

    The provider fields hold what both sides last agreed on; they are empty while the file's first
    upload is still under way (`upload_started_at`). `pending` is work only the Agent's pod can do:
    apply a user's edit, or re-upload the Agent's copy. A pod claims it until `lease_until`.
    """

    __tablename__: str = "sync_file"

    __table_args__ = (
        sa.Index(FILE_PATH_INDEX, "folder_id", sa.text("lower(path)"), unique=True),
        sa.Index(FILE_ITEM_INDEX, "folder_id", "item_id", unique=True),
    )

    folder_id: UUID = SqlField(foreign_key="sync_agent_folder.id", nullable=False, ondelete="CASCADE")
    path: str = SqlField(nullable=False, sa_type=sa.Text)
    item_id: str | None = SqlField(default=None, nullable=True)
    etag: str | None = SqlField(default=None, nullable=True)
    ctag: str | None = SqlField(default=None, nullable=True)
    remote_hash: str | None = SqlField(default=None, nullable=True)
    local_sha256: str = SqlField(nullable=False, max_length=64)
    size: int = SqlField(sa_column=Column(sa.BigInteger(), nullable=False))
    synced_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))
    upload_started_at: datetime | None = SqlField(
        default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )
    pending: SyncPendingAction | None = SqlField(default=None, sa_column=Column(sa.String(16), nullable=True))
    lease_until: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))
    attempts: int = SqlField(default=0, sa_column=Column(sa.Integer(), nullable=False, server_default="0"))
    retry_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))


class SyncActivity(BaseModel, table=True):
    """Something File Sync did that a person should be able to see. Kept after its folder is removed."""

    __tablename__: str = "sync_activity"

    __table_args__ = (sa.Index("ix_sync_activity_agent_occurred", "agent_id", "occurred_at"),)

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    folder_id: UUID | None = SqlField(
        default=None, foreign_key="sync_agent_folder.id", nullable=True, ondelete="SET NULL"
    )
    kind: SyncActivityKind = SqlField(sa_column=Column(sa.String(32), nullable=False))
    path: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text)
    detail: str | None = SqlField(default=None, nullable=True, sa_type=sa.Text)
    occurred_at: datetime = SqlField(sa_column=Column(sa.DateTime(timezone=True), nullable=False))


class FileSyncEntryCreate(PydanticBaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FileSyncChangesCreate(PydanticBaseModel):
    complete: bool
    entries: list[FileSyncEntryCreate] = Field(max_length=MAX_MANIFEST_ENTRIES)
