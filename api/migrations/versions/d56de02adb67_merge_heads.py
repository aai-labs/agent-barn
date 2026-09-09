"""merge heads

Revision ID: d56de02adb67
Revises: 87ec190e0f7d, a2d4f6b8c0e2
Create Date: 2026-09-04 10:18:59.815484

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d56de02adb67"
down_revision: str | Sequence[str] | None = ("87ec190e0f7d", "a2d4f6b8c0e2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
