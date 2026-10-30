"""merge heads

Revision ID: bbf41e2c5917
Revises: c7d2e9f4a1b3, fac0030afc38
Create Date: 2026-10-27 22:45:43.838025

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "bbf41e2c5917"
down_revision: str | tuple[str, ...] | None = ("c7d2e9f4a1b3", "fac0030afc38")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
