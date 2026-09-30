"""add verbose_mode to agent

Revision ID: a4b5c6d7e8f9
Revises: 87ec190e0f7d
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "87ec190e0f7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("verbose_mode", sa.Boolean(), nullable=True))
    op.execute("UPDATE agent SET verbose_mode = false WHERE verbose_mode IS NULL")
    op.alter_column("agent", "verbose_mode", nullable=False)


def downgrade() -> None:
    op.drop_column("agent", "verbose_mode")
