"""merge heads

Revision ID: ad8b4a278dd1
Revises: e4f5a6b7c8d9, e7a4b9c2d5f1
Create Date: 2026-07-27 16:42:36.816632

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ad8b4a278dd1"
down_revision: str | Sequence[str] | None = ("e4f5a6b7c8d9", "e7a4b9c2d5f1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
