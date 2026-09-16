"""merge heads

Revision ID: 6dffe1a40c83
Revises: a4b5c6d7e8f9, d56de02adb67
Create Date: 2026-09-07 12:03:50.970713

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6dffe1a40c83"
down_revision: str | Sequence[str] | None = ("a4b5c6d7e8f9", "d56de02adb67")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
