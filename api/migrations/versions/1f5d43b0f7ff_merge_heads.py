"""merge heads

Revision ID: 1f5d43b0f7ff
Revises: b7e2c41d9a63, bc817a73bb6d
Create Date: 2026-11-23 12:14:38.641512

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '1f5d43b0f7ff'
down_revision: str | Sequence[str] | None = ('b7e2c41d9a63', 'bc817a73bb6d')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
