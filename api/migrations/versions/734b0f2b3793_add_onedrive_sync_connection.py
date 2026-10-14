"""add onedrive sync connection

Revision ID: 734b0f2b3793
Revises: 0d612dc60e9a
Create Date: 2026-10-14

An Organization's connection to one SharePoint site through the platform Microsoft app,
for OneDrive sync. At most one row per Organization is open (pending or active);
disconnected rows are kept.
"""

import sqlalchemy as sa
from alembic import op

revision = "734b0f2b3793"
down_revision = "0d612dc60e9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onedrive_sync_connection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.String(), nullable=True),
        sa.Column("site_name", sa.String(), nullable=True),
        sa.Column("site_url", sa.String(), nullable=True),
        sa.Column("folder_item_id", sa.String(), nullable=True),
        sa.Column("folder_web_url", sa.String(), nullable=True),
        sa.Column("permission_id", sa.String(), nullable=True),
        sa.Column("pending_access_token", sa.String(), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["user.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "uq_onedrive_sync_connection_open",
        "onedrive_sync_connection",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )


def downgrade() -> None:
    op.drop_index("uq_onedrive_sync_connection_open", table_name="onedrive_sync_connection")
    op.drop_table("onedrive_sync_connection")
