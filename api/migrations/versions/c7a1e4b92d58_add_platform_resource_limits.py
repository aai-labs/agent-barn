"""Add platform_resource_limits

Revision ID: c7a1e4b92d58
Revises: 45bcefcb0749
Create Date: 2026-10-01

The capacity limits a Platform Administrator enters for the namespace (AF-170): the
ceilings on the total of container memory and CPU limits, which the tenant service account
cannot read from the cluster. One row at most, created on first save. No backfill: a missing
row and a NULL column both mean "no limit entered", so nothing warns until someone sets one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a1e4b92d58"
down_revision: str | Sequence[str] | None = "45bcefcb0749"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_resource_limits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("memory_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cpu_limit_cores", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_resource_limits")
