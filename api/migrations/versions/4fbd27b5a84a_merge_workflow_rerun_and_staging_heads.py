"""merge workflow rerun and staging heads

Revision ID: 4fbd27b5a84a
Revises: 63c0e8364607, c7d4e2a91b58
Create Date: 2026-10-29 15:42:56.335341

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4fbd27b5a84a"
down_revision: tuple[str, str] = ("63c0e8364607", "c7d4e2a91b58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
