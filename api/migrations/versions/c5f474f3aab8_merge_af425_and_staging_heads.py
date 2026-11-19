"""merge AF-425 and staging heads

Revision ID: c5f474f3aab8
Revises: 7aca1d608723, 3f9f88255e3b
Create Date: 2026-11-19 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c5f474f3aab8"
down_revision: str | tuple[str, ...] | None = ("7aca1d608723", "3f9f88255e3b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
