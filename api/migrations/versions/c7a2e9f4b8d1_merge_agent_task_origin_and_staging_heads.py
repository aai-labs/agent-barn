"""Merge agent task origin and agent file sync heads.

Revision ID: c7a2e9f4b8d1
Revises: f2c6d8a4b1e3, b9e4a7c2d3f6
Create Date: 2026-10-29 11:10:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c7a2e9f4b8d1"
down_revision: str | Sequence[str] | None = ("f2c6d8a4b1e3", "b9e4a7c2d3f6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
