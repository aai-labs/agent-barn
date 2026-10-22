"""organization agent limit

Revision ID: d8b3f1a6c925
Revises: c5e2a7d91f04
Create Date: 2026-10-13 12:00:00.000000

How many Agents an Organization may run (AF-381). NULL follows the default — the trial
setting for a trial, the deployment's for any other — so every existing Organization
keeps the limit it has today.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8b3f1a6c925"
down_revision: str | Sequence[str] | None = "c5e2a7d91f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("agent_limit", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "check_agent_limit_non_negative", "organization", "agent_limit IS NULL OR agent_limit >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("check_agent_limit_non_negative", "organization", type_="check")
    op.drop_column("organization", "agent_limit")
