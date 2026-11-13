"""merge OpenClaw Bots and Hermes Bots heads

Revision ID: d3c8e1f4a2b7
Revises: 865ce7d7db04, ed009c1e7a7c
Create Date: 2026-11-13 18:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d3c8e1f4a2b7"
down_revision: str | tuple[str, ...] | None = ("865ce7d7db04", "ed009c1e7a7c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
