"""Merge the managed update state history with staging's quota ceiling merge.

Revision ID: f1aac76e927a
Revises: 5c0e8d2a7f13, aaf767b06036
"""

from collections.abc import Sequence

revision: str = "f1aac76e927a"
down_revision: str | Sequence[str] | None = ("5c0e8d2a7f13", "aaf767b06036")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
