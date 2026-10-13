"""Merge Organization memory team keys with staging Personal API Keys.

Revision ID: e81c2a97b4f3
Revises: f69a2e0c847d, c055b65baf67
"""

from collections.abc import Sequence

revision: str = "e81c2a97b4f3"
down_revision: str | Sequence[str] | None = ("f69a2e0c847d", "c055b65baf67")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
