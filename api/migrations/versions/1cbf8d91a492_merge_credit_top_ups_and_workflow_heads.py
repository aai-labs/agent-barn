"""Merge credit top-ups and workflow heads.

Revision ID: 1cbf8d91a492
Revises: 0fc7f5e68d9d, 49e4d8bea6de
Create Date: 2026-10-20 13:31:39.139143

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "1cbf8d91a492"
down_revision: str | Sequence[str] | None = ("0fc7f5e68d9d", "49e4d8bea6de")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
