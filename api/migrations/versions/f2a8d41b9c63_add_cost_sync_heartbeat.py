"""Track completed cost syncs for the Agent Memory spend gate.

Revision ID: f2a8d41b9c63
Revises: e4c9b72a6f10
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "f2a8d41b9c63"
down_revision = "e4c9b72a6f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_sync_state",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cost_sync_state")
