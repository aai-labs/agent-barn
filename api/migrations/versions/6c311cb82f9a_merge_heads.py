"""merge heads

Revision ID: 6c311cb82f9a
Revises: da8ba7aeb850, f1aac76e927a
Create Date: 2026-10-09

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6c311cb82f9a"
down_revision: str | Sequence[str] | None = ("da8ba7aeb850", "f1aac76e927a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
