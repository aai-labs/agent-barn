"""add agent file sync switch

Revision ID: df10528f512f
Revises: af95cf4c3a1e
Create Date: 2026-10-26

AF-385: a per-Agent switch that turns File Sync off or on, on by default so existing Agents keep
syncing, and a per-folder request for the Sync Engine to re-check a folder after sync is turned on.
"""

import sqlalchemy as sa
from alembic import op

revision = "df10528f512f"
down_revision = "af95cf4c3a1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("file_sync_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "sync_agent_folder",
        sa.Column("resync_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_agent_folder", "resync_requested_at")
    op.drop_column("agent", "file_sync_enabled")
