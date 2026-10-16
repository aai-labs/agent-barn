"""Merge sync provider connection and Gmail/self-signup heads.

Revision ID: 877273bff59e
Revises: 0219de43e2c9, 5f2a7c9e1d84
Create Date: 2026-10-16 12:30:39.521699

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "877273bff59e"
down_revision: str | Sequence[str] | None = ("0219de43e2c9", "5f2a7c9e1d84")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
