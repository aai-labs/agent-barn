"""Merge agent tasks and staging heads.

Revision ID: a9d2e7c4b1f8
Revises: f1c6a8d3e5b7, c8e41f7a2d96
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a9d2e7c4b1f8"
down_revision: str | Sequence[str] | None = ("f1c6a8d3e5b7", "c8e41f7a2d96")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
