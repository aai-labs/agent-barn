"""merge heads

Revision ID: a7e3c1d9f2b4
Revises: bbf41e2c5917, 05548c9db068
Create Date: 2026-10-28 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a7e3c1d9f2b4"
down_revision: str | tuple[str, ...] | None = ("bbf41e2c5917", "05548c9db068")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
