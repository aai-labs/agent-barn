"""merge heads

Revision ID: c3d7e9a1f5b8
Revises: a7e3c1d9f2b4, 00cdd18a6e91
Create Date: 2026-10-28 10:10:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c3d7e9a1f5b8"
down_revision: str | tuple[str, ...] | None = ("a7e3c1d9f2b4", "00cdd18a6e91")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
