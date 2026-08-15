"""remove restored_from_version and draft source_version

Revision ID: 9a1b2c3d4e5f
Revises: 8c1e9cda45e3
Create Date: 2026-08-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a1b2c3d4e5f"
down_revision: str | None = "8c1e9cda45e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("skill_version", "restored_from_version")
    op.drop_column("skill_draft", "source_version")


def downgrade() -> None:
    op.add_column(
        "skill_draft",
        sa.Column("source_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "skill_version",
        sa.Column("restored_from_version", sa.Integer(), nullable=True),
    )
