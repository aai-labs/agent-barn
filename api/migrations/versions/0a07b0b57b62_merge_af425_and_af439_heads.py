"""merge AF-425 and AF-439 heads

Revision ID: 0a07b0b57b62
Revises: c5f474f3aab8, e4b439a1c7d2
Create Date: 2026-11-19 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0a07b0b57b62"
down_revision: str | tuple[str, ...] | None = ("c5f474f3aab8", "e4b439a1c7d2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
