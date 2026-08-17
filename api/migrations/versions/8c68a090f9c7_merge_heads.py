"""merge heads

Revision ID: 8c68a090f9c7
Revises: 4a7c2e9f1b63, a3d7f5e91c62
Create Date: 2026-08-11 19:50:36.881809

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8c68a090f9c7"
down_revision: str | Sequence[str] | None = ("4a7c2e9f1b63", "a3d7f5e91c62")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
