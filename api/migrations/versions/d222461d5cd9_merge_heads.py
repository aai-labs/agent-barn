"""merge heads

Revision ID: d222461d5cd9
Revises: a3c4e5f6b7d8, ee8815d37c1c
Create Date: 2026-08-04 20:29:45.619515

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d222461d5cd9"
down_revision: str | Sequence[str] | None = ("a3c4e5f6b7d8", "ee8815d37c1c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
