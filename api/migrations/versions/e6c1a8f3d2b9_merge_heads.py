"""merge heads

Revision ID: e6c1a8f3d2b9
Revises: d8a2f6c4e1b7, cd22e37ca5b8
Create Date: 2026-10-29 09:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e6c1a8f3d2b9"
down_revision: str | tuple[str, ...] | None = ("d8a2f6c4e1b7", "cd22e37ca5b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
