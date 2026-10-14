"""billing unapplied payments

Revision ID: d4a7c2e9f150
Revises: c9f6a4b2d318
Create Date: 2026-10-14 18:30:00.000000

Every payment that granted no credit (AF-381), so it goes on the platform audit log once,
and its refund or dispute is acknowledged rather than waiting for a purchase that will
never be recorded.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c2e9f150"
down_revision: str | Sequence[str] | None = "c9f6a4b2d318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_unapplied_payment",
        sa.Column("payment_reference", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("payment_reference"),
    )


def downgrade() -> None:
    op.drop_table("billing_unapplied_payment")
