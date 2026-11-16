"""merge AF-425 and subscriptions heads

Revision ID: 7aca1d608723
Revises: ed009c1e7a7c, 38de1199ae19
Create Date: 2026-11-16 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7aca1d608723"
down_revision: str | tuple[str, ...] | None = ("ed009c1e7a7c", "38de1199ae19")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
