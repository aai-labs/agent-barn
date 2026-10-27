"""index healed cost records

Revision ID: 218e1241a0c5
Revises: 897a48ad47f0
Create Date: 2026-10-19 11:17:05.034052

Healed spend is summed over an Organization's whole history on every budget check while
it runs on credit (AF-381). A partial index holds only the healed rows, so that sum no
longer walks every cost record the Organization has.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "218e1241a0c5"
down_revision: str | Sequence[str] | None = "897a48ad47f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_cost_record_healed_org_occurred",
        "cost_record",
        ["organization_id", "occurred_at"],
        postgresql_where=sa.text("healed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cost_record_healed_org_occurred", table_name="cost_record")
