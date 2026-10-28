"""merge heads

Revision ID: b5f8d2e6a3c9
Revises: a7e3c1d9f2b4, d4a9c6e2b7f1
Create Date: 2026-10-28 12:10:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b5f8d2e6a3c9"
down_revision: str | tuple[str, ...] | None = ("a7e3c1d9f2b4", "d4a9c6e2b7f1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
