"""A subscription's scheduled downgrade

Revision ID: fa0322c6cd7a
Revises: 0c24c221ee1e
Create Date: 2026-11-10

Moving to a smaller paid Tier takes effect when the period ends, so a subscription records
the Tier it moves to then, and the provider's own record of that change to take it back.
Both start empty: nothing is scheduled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa0322c6cd7a"
down_revision: str | Sequence[str] | None = "0c24c221ee1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization_subscription", sa.Column("scheduled_tier_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "organization_subscription_scheduled_tier_id_fkey",
        "organization_subscription",
        "tier",
        ["scheduled_tier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("organization_subscription", sa.Column("provider_schedule_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("organization_subscription", "provider_schedule_id")
    op.drop_constraint(
        "organization_subscription_scheduled_tier_id_fkey", "organization_subscription", type_="foreignkey"
    )
    op.drop_column("organization_subscription", "scheduled_tier_id")
