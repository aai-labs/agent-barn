"""merge heads

Revision ID: f2b7d9c4a6e1
Revises: e6c1a8f3d2b9, 63c0e8364607, c7d4e2a91b58
Create Date: 2026-10-30 09:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f2b7d9c4a6e1"
down_revision: str | tuple[str, ...] | None = ("e6c1a8f3d2b9", "63c0e8364607", "c7d4e2a91b58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
