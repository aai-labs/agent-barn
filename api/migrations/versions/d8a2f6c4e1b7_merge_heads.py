"""merge heads

Revision ID: d8a2f6c4e1b7
Revises: c3d7e9a1f5b8, b5f8d2e6a3c9
Create Date: 2026-10-28 10:15:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d8a2f6c4e1b7"
down_revision: str | tuple[str, ...] | None = ("c3d7e9a1f5b8", "b5f8d2e6a3c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
