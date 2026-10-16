"""add sync provider connection

Revision ID: 734b0f2b3793
Revises: 0d612dc60e9a
Create Date: 2026-10-14

An Organization's connection to one storage provider (OneDrive first). At most one row per
Organization is open (pending or active); disconnected rows are kept.
"""

import sqlalchemy as sa
from alembic import op

revision = "734b0f2b3793"
down_revision = "0d612dc60e9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_provider_connection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.String(), nullable=True),
        sa.Column("location_name", sa.String(), nullable=True),
        sa.Column("location_url", sa.String(), nullable=True),
        sa.Column("folder_id", sa.String(), nullable=True),
        sa.Column("folder_web_url", sa.String(), nullable=True),
        sa.Column("provider_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.CheckConstraint("schema_version > 0", name="ck_sync_provider_connection_schema_version"),
    )
    op.create_index(
        "uq_sync_provider_connection_open",
        "sync_provider_connection",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_provider_connection_open", table_name="sync_provider_connection")
    op.drop_table("sync_provider_connection")
