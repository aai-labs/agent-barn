"""merge heads

Revision ID: c055b65baf67
Revises: d7a2c4f81b36, e4b9d72c160a
Create Date: 2026-10-05 17:45:31.492286

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c055b65baf67"
down_revision: str | Sequence[str] | None = ("d7a2c4f81b36", "e4b9d72c160a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
