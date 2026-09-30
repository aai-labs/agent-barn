"""add organization budget email receipt

Revision ID: c3e6a91b47d2
Revises: b2d5f8a34c71
Create Date: 2026-09-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e6a91b47d2"
down_revision: str | Sequence[str] | None = "b2d5f8a34c71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_budget_email_receipt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_org_budget_email_receipt_delivery_recipient"),
    )
    op.create_index(
        "ix_organization_budget_email_receipt_delivery_id",
        "organization_budget_email_receipt",
        ["delivery_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_budget_email_receipt_delivery_id",
        table_name="organization_budget_email_receipt",
    )
    op.drop_table("organization_budget_email_receipt")
