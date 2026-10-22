"""credit ledger

Revision ID: c5e2a7d91f04
Revises: b3d8e1f4a6c2
Create Date: 2026-10-13 09:00:00.000000

The credit ledger (AF-381): every change to an Organization's credit, whose sum is the
ceiling of an Organization on credit. Each Organization already on credit opens its
ledger with its current ceiling — as trial credit while it is a trial, as an adjustment
once it is not — so the ledger adds up to the ceiling from the start. Organizations on a
renewing limit get no ledger.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e2a7d91f04"
down_revision: str | Sequence[str] | None = "b3d8e1f4a6c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ("TRIAL", "PURCHASE", "REFUND", "CHARGEBACK", "ADJUSTMENT")


def upgrade() -> None:
    op.create_table(
        "organization_credit_grant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum(*_KINDS, name="credit_grant_kind"), nullable=False),
        sa.Column("credit_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_paid_usd", sa.Numeric(14, 2), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("actor_display", sa.String(length=255), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_ref"),
    )
    op.create_index("ix_organization_credit_grant_organization_id", "organization_credit_grant", ["organization_id"])
    op.execute(
        """
        INSERT INTO organization_credit_grant
            (id, created_at, updated_at, organization_id, kind, credit_usd, actor_display)
        SELECT gen_random_uuid(), now(), now(), id,
               CASE WHEN is_trial THEN 'TRIAL' ELSE 'ADJUSTMENT' END::credit_grant_kind,
               llm_budget_usd, 'Opening balance'
        FROM organization
        WHERE llm_budget_duration = 'once'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_organization_credit_grant_organization_id", table_name="organization_credit_grant")
    op.drop_table("organization_credit_grant")
    sa.Enum(name="credit_grant_kind").drop(op.get_bind(), checkfirst=True)
