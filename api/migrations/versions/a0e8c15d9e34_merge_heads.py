"""merge heads

Revision ID: a0e8c15d9e34
Revises: 6f0c4b526072, c8e1f4a9b2d6
Create Date: 2026-09-17 18:18:49.655866

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a0e8c15d9e34"
down_revision: str | None = ("6f0c4b526072", "c8e1f4a9b2d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
