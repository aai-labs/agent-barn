"""Merge native gateway retirement and self-service spend-limit histories.

Revision ID: 2519037fd3ea
Revises: 8b1d5e7f9a23, d7a2c4f81b36
"""

from collections.abc import Sequence

revision: str = "2519037fd3ea"
down_revision: str | Sequence[str] | None = ("8b1d5e7f9a23", "d7a2c4f81b36")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
