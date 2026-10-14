"""trial expiry

Revision ID: e4a9c2d7b318
Revises: d8b3f1a6c925
Create Date: 2026-10-13 15:00:00.000000

When a trial ran out of credit (AF-381). An expired trial stays a trial but no longer
counts toward the cap on active trials. A trial already alerted at 100% of its credit is
expired now: that alert is what expires a trial, and it won't be sent again. The alert,
not the spend snapshot, because it also counts spend the proxy doesn't see.

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
        "WHERE is_trial AND llm_alerted_threshold IS NOT NULL AND llm_alerted_threshold >= 100"
    )


def downgrade() -> None:
    op.drop_column("organization", "trial_expired_at")
