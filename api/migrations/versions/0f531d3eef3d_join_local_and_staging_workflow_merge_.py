"""join local and staging workflow merge heads

Revision ID: 0f531d3eef3d
Revises: 4fbd27b5a84a, 921deb774e01
Create Date: 2026-10-30 10:08:33.253849

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0f531d3eef3d"
down_revision: tuple[str, str] = ("4fbd27b5a84a", "921deb774e01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
