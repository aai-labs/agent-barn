"""merge gmail and self-signup heads

Revision ID: 5f2a7c9e1d84
Revises: 4b9e2d7c1a35, d72b85f19c40
Create Date: 2026-10-16

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5f2a7c9e1d84"
down_revision: str | Sequence[str] | None = ("4b9e2d7c1a35", "d72b85f19c40")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
