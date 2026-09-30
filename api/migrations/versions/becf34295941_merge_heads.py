"""merge heads

Revision ID: becf34295941
Revises: 2b89b1023b35, 6dffe1a40c83
Create Date: 2026-09-08 12:02:57.502951

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "becf34295941"
down_revision: str | Sequence[str] | None = ("2b89b1023b35", "6dffe1a40c83")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
