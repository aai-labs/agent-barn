"""Put an Organization on a Tier

Revision ID: 9b0aec4da777
Revises: 55e07653f502
Create Date: 2026-11-08

Tiers, PR 2: `organization.tier_id` names the Tier an Organization is on. NULL keeps it
platform-managed and unrestricted, which is where every existing Organization stays, so
behavior is unchanged until a Platform Administrator assigns one. A Tier that Organizations
are on cannot be deleted (`ON DELETE RESTRICT`).

`tier_assigned_by_platform` records that a Platform Administrator chose the Tier, so a later
payment provider event will not replace it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b0aec4da777"
down_revision: str | Sequence[str] | None = "55e07653f502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("tier_id", sa.Uuid(), nullable=True))
    op.add_column(
        "organization",
        sa.Column("tier_assigned_by_platform", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_foreign_key(
        "fk_organization_tier_id_tier", "organization", "tier", ["tier_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_organization_tier_id", "organization", ["tier_id"])


def downgrade() -> None:
    op.drop_index("ix_organization_tier_id", table_name="organization")
    op.drop_constraint("fk_organization_tier_id_tier", "organization", type_="foreignkey")
    op.drop_column("organization", "tier_assigned_by_platform")
    op.drop_column("organization", "tier_id")
