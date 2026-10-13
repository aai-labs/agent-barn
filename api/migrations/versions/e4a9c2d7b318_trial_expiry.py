"""trial expiry

Revision ID: e4a9c2d7b318
Revises: d8b3f1a6c925
Create Date: 2026-10-13 15:00:00.000000

When a trial ran out of credit (AF-381). An expired trial stays a trial but no longer
counts toward the cap on active trials. A trial already out of credit by its last spend
snapshot is expired now: its budget alert has already been sent and won't be again.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a9c2d7b318"
down_revision: str | Sequence[str] | None = "d8b3f1a6c925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("trial_expired_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE organization SET trial_expired_at = now() "
        "WHERE is_trial AND llm_spend_usd IS NOT NULL AND llm_spend_usd >= llm_budget_usd"
    )


def downgrade() -> None:
    op.drop_column("organization", "trial_expired_at")
