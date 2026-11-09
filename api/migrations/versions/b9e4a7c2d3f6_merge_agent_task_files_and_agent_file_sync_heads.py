"""Merge agent task files and agent file sync heads.

Revision ID: b9e4a7c2d3f6
Revises: e8b3f1a2c4d5, cd22e37ca5b8
Create Date: 2026-10-29 11:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b9e4a7c2d3f6"
down_revision: str | Sequence[str] | None = ("e8b3f1a2c4d5", "cd22e37ca5b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
