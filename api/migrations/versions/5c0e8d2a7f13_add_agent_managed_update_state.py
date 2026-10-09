"""Record a running managed update on its Agent, and how the last one ended.

Revision ID: 5c0e8d2a7f13
Revises: 3775f7e14775
"""

import sqlalchemy as sa
from alembic import op

revision: str = "5c0e8d2a7f13"
down_revision: str | None = "3775f7e14775"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("managed_update_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent", sa.Column("managed_update_outcome", sa.String(20), nullable=True))
    op.add_column("agent", sa.Column("managed_update_restore_point_id", sa.Uuid(), nullable=True))
    op.add_column("agent", sa.Column("managed_update_failure_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "managed_update_failure_reason")
    op.drop_column("agent", "managed_update_restore_point_id")
    op.drop_column("agent", "managed_update_outcome")
    op.drop_column("agent", "managed_update_heartbeat_at")
