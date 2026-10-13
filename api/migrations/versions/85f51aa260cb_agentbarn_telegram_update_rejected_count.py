"""agentbarn telegram update rejected count

Revision ID: 85f51aa260cb
Revises: dfcfdf34eefa
Create Date: 2026-10-12 17:00:00.000000

Counts the times an Agent's webhook refused a shared-bot update, apart from
attempts that could not reach the pod, so a refused update is dropped after a
few tries instead of holding back its sender's later updates for a day.
Existing rows start at zero.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "85f51aa260cb"
down_revision: str | Sequence[str] | None = "dfcfdf34eefa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agentbarn_telegram_update",
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agentbarn_telegram_update", "rejected_count")
