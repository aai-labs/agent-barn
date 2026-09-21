"""merge heads

Revision ID: b8518034a825
Revises: 97f14c9b7000, d4f1a8c2e3b7
Create Date: 2026-09-21 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b8518034a825"
down_revision: str | Sequence[str] | None = ("97f14c9b7000", "d4f1a8c2e3b7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
