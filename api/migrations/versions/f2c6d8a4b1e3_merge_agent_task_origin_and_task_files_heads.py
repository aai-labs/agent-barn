"""Merge agent task origin and agent task files heads.

Revision ID: f2c6d8a4b1e3
Revises: 4c880a72e056, e8b3f1a2c4d5
Create Date: 2026-10-29 10:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f2c6d8a4b1e3"
down_revision: str | Sequence[str] | None = ("4c880a72e056", "e8b3f1a2c4d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
