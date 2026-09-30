"""merge heads

Revision ID: ee946cc4a3c3
Revises: af0a523a3dd6, e0f1a2b3c4d5
Create Date: 2026-08-28 13:20:41.364610

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ee946cc4a3c3"
down_revision: str | Sequence[str] | None = ("af0a523a3dd6", "e0f1a2b3c4d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
