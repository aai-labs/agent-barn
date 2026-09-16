"""add cancel_requested_at to communication_delivery

Revision ID: a2d4f6b8c0e2
Revises: 4fb2ac67de91
Create Date: 2026-09-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2d4f6b8c0e2"
down_revision: str | Sequence[str] | None = "4fb2ac67de91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communication_delivery",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_delivery", "cancel_requested_at")
