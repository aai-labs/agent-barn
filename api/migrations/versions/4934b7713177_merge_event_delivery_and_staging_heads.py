"""merge event delivery and staging heads

Revision ID: 4934b7713177
Revises: d1e2f3a4b5c6, f8d2c3e4b5a6
Create Date: 2026-07-28 23:57:50.170091

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4934b7713177"
down_revision: str | Sequence[str] | None = ("d1e2f3a4b5c6", "f8d2c3e4b5a6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
