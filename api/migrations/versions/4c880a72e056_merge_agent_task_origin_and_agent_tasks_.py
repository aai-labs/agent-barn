"""Merge agent task origin and agent tasks heads.

Revision ID: 4c880a72e056
Revises: 8b2817cf6991, 3fb664907ef8
Create Date: 2026-10-27 10:08:16.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4c880a72e056"
down_revision: str | Sequence[str] | None = ("8b2817cf6991", "3fb664907ef8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
