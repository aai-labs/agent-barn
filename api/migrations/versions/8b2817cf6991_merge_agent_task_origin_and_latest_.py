"""Merge agent task origin and latest staging heads.

Revision ID: 8b2817cf6991
Revises: e5a1c9f3d208, b9e32d74a610
Create Date: 2026-10-23 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8b2817cf6991"
down_revision: str | Sequence[str] | None = ("e5a1c9f3d208", "b9e32d74a610")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
