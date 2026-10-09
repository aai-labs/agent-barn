"""Merge native gateway retirement and personal API key histories.

Revision ID: a309cd8a0ccc
Revises: 2519037fd3ea, c055b65baf67
"""

from collections.abc import Sequence

revision: str = "a309cd8a0ccc"
down_revision: str | Sequence[str] | None = ("2519037fd3ea", "c055b65baf67")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
