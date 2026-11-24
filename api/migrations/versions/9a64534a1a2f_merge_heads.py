"""merge heads

Revision ID: 9a64534a1a2f
Revises: 1f5d43b0f7ff, 92996d692c89
Create Date: 2026-11-23 13:58:27.361403

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9a64534a1a2f"
down_revision: str | Sequence[str] | None = ("1f5d43b0f7ff", "92996d692c89")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
