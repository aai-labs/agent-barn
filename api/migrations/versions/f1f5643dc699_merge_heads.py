"""merge heads

Revision ID: f1f5643dc699
Revises: 3b7c9d1e4f62, b3f7c1d92a04
Create Date: 2026-08-03 00:47:46.389613

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f1f5643dc699"
down_revision: str | Sequence[str] | None = ("3b7c9d1e4f62", "b3f7c1d92a04")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
