"""merge heads

Revision ID: d4a9c6e2b7f1
Revises: bbf41e2c5917, e3b8d1f5a7c2
Create Date: 2026-10-27 23:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d4a9c6e2b7f1"
down_revision: str | tuple[str, ...] | None = ("bbf41e2c5917", "e3b8d1f5a7c2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
