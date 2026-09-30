"""Merge Agent Settings and Communications heads.

Revision ID: d02c31a1bb9f
Revises: a17857e799a1, f39d7aa422be
Create Date: 2026-08-26
"""

from collections.abc import Sequence

revision: str = "d02c31a1bb9f"
down_revision: str | Sequence[str] | None = ("a17857e799a1", "f39d7aa422be")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
