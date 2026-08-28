"""merge heads

Revision ID: f39d7aa422be
Revises: 8f5c1a6e4b93, c9f1b30a7d42, 9b4c7d2e6f10
Create Date: 2026-08-25 16:16:00.107981

"""

from collections.abc import Sequence

revision: str = "f39d7aa422be"
down_revision: str | Sequence[str] | None = ("8f5c1a6e4b93", "c9f1b30a7d42", "9b4c7d2e6f10")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
