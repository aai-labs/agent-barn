"""merge AF-445 and staging heads

Revision ID: c87b17ccfe1a
Revises: 3e9d8fca9996, 0a07b0b57b62
Create Date: 2026-11-19 18:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c87b17ccfe1a"
down_revision: str | tuple[str, ...] | None = ("3e9d8fca9996", "0a07b0b57b62")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
