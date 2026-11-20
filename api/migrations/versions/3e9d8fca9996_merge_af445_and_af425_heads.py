"""merge AF-445 and AF-425 heads

Revision ID: 3e9d8fca9996
Revises: d3c8e1f4a2b7, 7aca1d608723
Create Date: 2026-11-16 15:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "3e9d8fca9996"
down_revision: str | tuple[str, ...] | None = ("d3c8e1f4a2b7", "7aca1d608723")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
