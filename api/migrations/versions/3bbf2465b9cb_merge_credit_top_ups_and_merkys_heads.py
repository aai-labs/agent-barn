"""Merge credit top-ups and Merkys heads.

Revision ID: 3bbf2465b9cb
Revises: 1cbf8d91a492, a4e9c2d7b615
Create Date: 2026-10-21 10:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "3bbf2465b9cb"
down_revision: str | Sequence[str] | None = ("1cbf8d91a492", "a4e9c2d7b615")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
