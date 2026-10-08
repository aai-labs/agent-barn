"""add organization llm spend snapshot

Revision ID: b2d5f8a34c71
Revises: a1c4e9b27d55
Create Date: 2026-09-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d5f8a34c71"
down_revision: str | Sequence[str] | None = "a1c4e9b27d55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("llm_spend_usd", sa.Float(), nullable=True))
    op.add_column("organization", sa.Column("llm_spend_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization", sa.Column("llm_budget_renews_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization", sa.Column("llm_alerted_threshold", sa.Integer(), nullable=True))
    op.add_column("organization", sa.Column("llm_alert_key", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("organization", "llm_alert_key")
    op.drop_column("organization", "llm_alerted_threshold")
    op.drop_column("organization", "llm_budget_renews_at")
    op.drop_column("organization", "llm_spend_observed_at")
    op.drop_column("organization", "llm_spend_usd")
