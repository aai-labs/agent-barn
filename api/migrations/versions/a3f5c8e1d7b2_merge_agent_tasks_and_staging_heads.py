"""Merge agent tasks and staging heads.

Revision ID: a3f5c8e1d7b2
Revises: b9e4a7c2d3f6, 91d534425109
Create Date: 2026-11-06 07:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a3f5c8e1d7b2"
down_revision: str | Sequence[str] | None = ("b9e4a7c2d3f6", "91d534425109")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
