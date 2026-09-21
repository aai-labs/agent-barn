"""merge heads

Revision ID: 4b4bb4af4d31
Revises: b8518034a825, 43ac1fbc7ff1
Create Date: 2026-09-21 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4b4bb4af4d31"
down_revision: str | Sequence[str] | None = ("b8518034a825", "43ac1fbc7ff1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
