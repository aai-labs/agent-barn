"""add agent file sync

Revision ID: af95cf4c3a1e
Revises: a4e9c2d7b615
Create Date: 2026-10-21

AF-384: each Agent's folder at the Organization's Sync Provider, each synced file with any work
only the Agent's pod can do, and the activity a person can read. The connection gains the
provider's change cursor and a throttling retry time.
"""

import sqlalchemy as sa
from alembic import op

revision = "af95cf4c3a1e"
down_revision = "a4e9c2d7b615"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("sync_provider_connection", sa.Column("sync_cursor", sa.Text(), nullable=True))
    op.add_column("sync_provider_connection", sa.Column("sync_retry_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "sync_agent_folder",
        *_base_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("folder_name", sa.String(length=255), nullable=False),
        sa.Column("folder_item_id", sa.String(), nullable=True),
        sa.Column("folder_web_url", sa.String(), nullable=True),
        sa.Column("folder_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["sync_provider_connection.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_sync_agent_folder_connection_agent", "sync_agent_folder", ["connection_id", "agent_id"], unique=True
    )
    op.create_index(
        "uq_sync_agent_folder_connection_name",
        "sync_agent_folder",
        ["connection_id", sa.text("lower(folder_name)")],
        unique=True,
    )

    op.create_table(
        "sync_file",
        *_base_columns(),
        sa.Column("folder_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("ctag", sa.String(), nullable=True),
        sa.Column("remote_hash", sa.String(), nullable=True),
        sa.Column("local_sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upload_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending", sa.String(length=16), nullable=True),
        sa.Column("pending_activity", sa.String(length=32), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["folder_id"], ["sync_agent_folder.id"], ondelete="CASCADE"),
    )
    op.create_index("uq_sync_file_folder_path", "sync_file", ["folder_id", sa.text("lower(path)")], unique=True)
    op.create_index("uq_sync_file_folder_item", "sync_file", ["folder_id", "item_id"], unique=True)

    op.create_table(
        "sync_activity",
        *_base_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["sync_agent_folder.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sync_activity_agent_occurred", "sync_activity", ["agent_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_activity_agent_occurred", table_name="sync_activity")
    op.drop_table("sync_activity")
    op.drop_index("uq_sync_file_folder_item", table_name="sync_file")
    op.drop_index("uq_sync_file_folder_path", table_name="sync_file")
    op.drop_table("sync_file")
    op.drop_index("uq_sync_agent_folder_connection_name", table_name="sync_agent_folder")
    op.drop_index("uq_sync_agent_folder_connection_agent", table_name="sync_agent_folder")
    op.drop_table("sync_agent_folder")
    op.drop_column("sync_provider_connection", "sync_retry_at")
    op.drop_column("sync_provider_connection", "sync_cursor")
