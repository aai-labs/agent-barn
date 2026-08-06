"""merge heads

Revision ID: 717d83f33baf
Revises: 1aa6ed23c288, 71a0d9a1a91d
Create Date: 2026-08-06 11:34:10.858555

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "717d83f33baf"
down_revision: str | Sequence[str] | None = ("1aa6ed23c288", "71a0d9a1a91d")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
