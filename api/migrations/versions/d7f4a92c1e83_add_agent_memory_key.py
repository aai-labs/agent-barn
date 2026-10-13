"""add hashed per-start Agent Memory credentials

Revision ID: d7f4a92c1e83
Revises: c3e8a1f4d927
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7f4a92c1e83"
down_revision: str | Sequence[str] | None = "c3e8a1f4d927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("memory_key_hash", sa.String(64), nullable=True))
    op.create_index("ix_agent_memory_key_hash", "agent", ["memory_key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_memory_key_hash", table_name="agent")
    op.drop_column("agent", "memory_key_hash")
