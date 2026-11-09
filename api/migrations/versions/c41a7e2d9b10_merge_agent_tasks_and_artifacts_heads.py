"""Merge agent tasks and artifacts heads.

Revision ID: c41a7e2d9b10
Revises: 3fb664907ef8, 00cdd18a6e91
Create Date: 2026-10-28 10:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c41a7e2d9b10"
down_revision: str | Sequence[str] | None = ("3fb664907ef8", "00cdd18a6e91")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
