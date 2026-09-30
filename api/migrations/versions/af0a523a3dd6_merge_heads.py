"""merge heads

Revision ID: af0a523a3dd6
Revises: b6c7d8e9f0a1, d02c31a1bb9f
Create Date: 2026-08-27 22:43:46.590424

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "af0a523a3dd6"
down_revision: str | Sequence[str] | None = ("b6c7d8e9f0a1", "d02c31a1bb9f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
