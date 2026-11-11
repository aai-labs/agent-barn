"""Subscriptions, and a paid Tier's credit on the ledger

Revision ID: 38de1199ae19
Revises: 86bca32c95be
Create Date: 2026-11-08

`organization_subscription` keeps an Organization on a paid Tier, whichever provider takes
the payment; at most one per Organization is live. It records the smaller Tier a downgrade
moves to when the period ends, with the provider's record of that change, and when
activation finished, so one that stopped partway is taken up again. Three Credit Grant kinds
record what a paid Tier grants: its one-time credit, each period's allowance, and what is
left of an allowance when its period ends.

Postgres can't drop a value from an enum, so the downgrade keeps the three kinds; nothing
writes them once the code that does is gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "38de1199ae19"
down_revision: str | Sequence[str] | None = "86bca32c95be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_KINDS = ("TIER_CREDIT", "ALLOWANCE", "ALLOWANCE_EXPIRY")


def upgrade() -> None:
    for kind in _NEW_KINDS:
        op.execute(f"ALTER TYPE credit_grant_kind ADD VALUE IF NOT EXISTS '{kind}'")
    op.create_table(
        "organization_subscription",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("tier_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_tier_id", sa.Uuid(), nullable=True),
        sa.Column("provider_schedule_id", sa.String(length=255), nullable=True),
        sa.Column("period_allowance_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("period_spend_start_usd", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tier_id"], ["tier.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["scheduled_tier_id"],
            ["tier.id"],
            name="organization_subscription_scheduled_tier_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_organization_subscription_provider_reference"
        ),
        sa.CheckConstraint("status IN ('active', 'past_due', 'canceled')", name="ck_organization_subscription_status"),
        sa.CheckConstraint("current_period_end > current_period_start", name="ck_organization_subscription_period"),
    )
    op.create_index("ix_organization_subscription_organization_id", "organization_subscription", ["organization_id"])
    op.create_index(
        "uq_organization_subscription_live",
        "organization_subscription",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'canceled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_organization_subscription_live", table_name="organization_subscription")
    op.drop_index("ix_organization_subscription_organization_id", table_name="organization_subscription")
    op.drop_table("organization_subscription")
