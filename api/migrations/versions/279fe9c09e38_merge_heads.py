"""merge heads

Revision ID: 279fe9c09e38
Revises: 8c4d2e7f9a10, b7c9d1e3f5a7
Create Date: 2026-08-31 18:20:59.491191

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "279fe9c09e38"
down_revision: str | Sequence[str] | None = ("8c4d2e7f9a10", "b7c9d1e3f5a7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
