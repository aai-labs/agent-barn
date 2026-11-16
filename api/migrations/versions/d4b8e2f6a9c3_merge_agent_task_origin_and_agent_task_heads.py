"""Merge agent task origin and agent task heads.

Revision ID: d4b8e2f6a9c3
Revises: c7a2e9f4b8d1, a3f5c8e1d7b2
Create Date: 2026-11-06 07:10:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d4b8e2f6a9c3"
down_revision: str | Sequence[str] | None = ("c7a2e9f4b8d1", "a3f5c8e1d7b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
