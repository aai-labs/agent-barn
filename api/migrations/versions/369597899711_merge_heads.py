"""merge heads

Revision ID: 369597899711
Revises: 82b57eb2e598, b6c7d8e9f0a1
Create Date: 2026-08-26 14:32:05.800639

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "369597899711"
down_revision: str | Sequence[str] | None = ("82b57eb2e598", "b6c7d8e9f0a1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
