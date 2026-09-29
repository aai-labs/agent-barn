"""add agent memory key

Revision ID: d5f9b2e8a314
Revises: c4e8a1d7f203
Create Date: 2026-09-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f9b2e8a314"
down_revision: str | Sequence[str] | None = "c4e8a1d7f203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("memory_key_encrypted", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "memory_key_encrypted")
