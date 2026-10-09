"""merge AF-363 runtime pin with staging AF-170

Revision ID: 3775f7e14775
Revises: 69011ec264e7, be043fdf21b3
Create Date: 2026-10-06 22:16:56.092917

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "3775f7e14775"
down_revision: str | Sequence[str] | None = ("69011ec264e7", "be043fdf21b3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
