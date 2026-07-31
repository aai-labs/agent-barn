"""merge heads

Revision ID: dce8d344498a
Revises: a6f2c9d18e47, e1f2a3b4c5d6
Create Date: 2026-07-23 14:11:36.228894

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "dce8d344498a"
down_revision: str | Sequence[str] | None = ("a6f2c9d18e47", "e1f2a3b4c5d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
