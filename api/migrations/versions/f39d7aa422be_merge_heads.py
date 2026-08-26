"""merge heads

Revision ID: f39d7aa422be
Revises: 82b57eb2e598, 8f5c1a6e4b93
Create Date: 2026-08-25 16:16:00.107981

"""

from collections.abc import Sequence

revision: str = "f39d7aa422be"
down_revision: str | Sequence[str] | None = ("82b57eb2e598", "8f5c1a6e4b93")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
