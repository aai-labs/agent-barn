"""merge heads

Revision ID: 82b57eb2e598
Revises: 9b4c7d2e6f10, c9f1b30a7d42
Create Date: 2026-08-25 12:32:20.575839

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "82b57eb2e598"
down_revision: str | Sequence[str] | None = ("9b4c7d2e6f10", "c9f1b30a7d42")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
