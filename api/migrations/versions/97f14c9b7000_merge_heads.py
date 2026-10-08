"""merge heads

Revision ID: 97f14c9b7000
Revises: c3e6a91b47d2, c4e8a2f19d73
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "97f14c9b7000"
down_revision: str | Sequence[str] | None = ("c3e6a91b47d2", "c4e8a2f19d73")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
