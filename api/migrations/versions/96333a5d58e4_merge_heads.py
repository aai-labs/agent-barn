"""merge heads

Revision ID: 96333a5d58e4
Revises: 609f9a8a428f, b4127aa08b89
Create Date: 2026-08-03 15:21:01.090130

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "96333a5d58e4"
down_revision: str | Sequence[str] | None = ("609f9a8a428f", "b4127aa08b89")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
