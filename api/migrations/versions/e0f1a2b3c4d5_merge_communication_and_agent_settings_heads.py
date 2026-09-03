"""Merge communication journal and Agent Settings migration heads.

Revision ID: e0f1a2b3c4d5
Revises: b7c8d9e0f1a2, d02c31a1bb9f
Create Date: 2026-08-27

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: str | Sequence[str] | None = ("b7c8d9e0f1a2", "d02c31a1bb9f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
