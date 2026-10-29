"""billing

Revision ID: f1c7e3a92b05
Revises: e4a9c2d7b318
Create Date: 2026-10-13 18:00:00.000000

Buying credit with Stripe (AF-381): the platform's billing settings (a singleton; the
defaults apply until the first save), each Organization's Stripe Customer, and the
`billing.manage` Permission, which only Owners hold.

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "f1c7e3a92b05"
down_revision: str | Sequence[str] | None = "e4a9c2d7b318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when it
# shipped, whatever the catalogue in code says later.
BILLING_MANAGE_ID = UUID("9a3e6c1f-2b74-5d08-8e5a-4c7f1b2d6e33")
BILLING_MANAGE_KEY = "billing.manage"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.create_table(
        "platform_billing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("min_purchase_usd", sa.Float(), nullable=False),
        sa.Column("max_purchase_usd", sa.Float(), nullable=False),
        sa.Column("credit_rate", sa.Float(), nullable=False),
        sa.Column("purchase_fee_percent", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_billing_settings_singleton"),
        sa.CheckConstraint("min_purchase_usd > 0", name="ck_platform_billing_settings_min_positive"),
        sa.CheckConstraint("max_purchase_usd >= min_purchase_usd", name="ck_platform_billing_settings_max_above_min"),
        sa.CheckConstraint("credit_rate > 0", name="ck_platform_billing_settings_rate_positive"),
        sa.CheckConstraint("purchase_fee_percent >= 0", name="ck_platform_billing_settings_fee_non_negative"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organization_billing_customer",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id"),
        sa.UniqueConstraint("stripe_customer_id"),
    )
    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=BILLING_MANAGE_ID,
        key=BILLING_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=BILLING_MANAGE_ID)
    op.drop_table("organization_billing_customer")
    op.drop_table("platform_billing_settings")
