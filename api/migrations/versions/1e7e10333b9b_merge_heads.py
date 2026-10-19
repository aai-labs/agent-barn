"""merge heads

Revision ID: 1e7e10333b9b
Revises: 5f2a7c9e1d84, e202cc84743b
Create Date: 2026-10-16 15:36:32.778646

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "1e7e10333b9b"
down_revision: str | Sequence[str] | None = ("5f2a7c9e1d84", "e202cc84743b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
