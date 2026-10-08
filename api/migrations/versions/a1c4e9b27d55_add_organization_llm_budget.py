"""add organization llm budget

Revision ID: a1c4e9b27d55
Revises: b3d1f47c9a20
Create Date: 2026-09-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4e9b27d55"
down_revision: str | Sequence[str] | None = "b3d1f47c9a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("llm_budget_usd", sa.Float(), nullable=True))
    op.add_column("organization", sa.Column("llm_budget_duration", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        "check_llm_budget_non_negative",
        "organization",
        "llm_budget_usd IS NULL OR llm_budget_usd >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("check_llm_budget_non_negative", "organization", type_="check")
    op.drop_column("organization", "llm_budget_duration")
    op.drop_column("organization", "llm_budget_usd")
