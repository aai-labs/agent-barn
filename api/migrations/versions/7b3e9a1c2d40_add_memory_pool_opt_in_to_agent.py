"""add memory pool opt-in to agent

Revision ID: 7b3e9a1c2d40
Revises: 65f92c323854
Branch Labels: None
Depends On: None

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3e9a1c2d40"
down_revision: str | None = "65f92c323854"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("agent", sa.Column("memory_pool_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "memory_pool_id")
    op.drop_column("agent", "memory_enabled")
