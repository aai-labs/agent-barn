"""Track locked provider items without holding up the change cursor.

Revision ID: 3680352c132d
Revises: 0f531d3eef3d
"""

import sqlalchemy as sa
from alembic import op

revision = "3680352c132d"
down_revision = "0f531d3eef3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_locked_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "connection_id", sa.Uuid(), sa.ForeignKey("sync_provider_connection.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.UniqueConstraint("connection_id", "item_id", name="uq_sync_locked_item"),
    )
    op.create_index("ix_sync_locked_item_connection_id", "sync_locked_item", ["connection_id"])


def downgrade() -> None:
    op.drop_table("sync_locked_item")
