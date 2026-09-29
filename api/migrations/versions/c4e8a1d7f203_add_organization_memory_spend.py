"""add organization memory spend and suspension

Revision ID: c4e8a1d7f203
Revises: 950b3e66140a
Create Date: 2026-09-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1d7f203"
down_revision: str | Sequence[str] | None = "950b3e66140a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("llm_memory_spend_usd", sa.Float(), nullable=True))
    op.add_column("organization", sa.Column("llm_memory_spend_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization", sa.Column("llm_memory_suspended_key", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("organization", "llm_memory_suspended_key")
    op.drop_column("organization", "llm_memory_spend_observed_at")
    op.drop_column("organization", "llm_memory_spend_usd")
