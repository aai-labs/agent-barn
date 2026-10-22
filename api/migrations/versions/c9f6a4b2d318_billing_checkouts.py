"""billing checkouts

Revision ID: c9f6a4b2d318
Revises: b8e5f3a1c207
Create Date: 2026-10-14 15:00:00.000000

Every Stripe Checkout Session we create, with the credit, charge, Organization and buyer
it was for (AF-381). The webhook grants what this record says, and only when Stripe's
session matches it, rather than trusting the session's own metadata.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f6a4b2d318"
down_revision: str | Sequence[str] | None = "b8e5f3a1c207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_checkout",
        sa.Column("stripe_session_id", sa.String(length=255), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("credit_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("purchased_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_billing_checkout_amount_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchased_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("stripe_session_id"),
    )
    op.create_index("ix_billing_checkout_organization_id", "billing_checkout", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_checkout_organization_id", table_name="billing_checkout")
    op.drop_table("billing_checkout")
