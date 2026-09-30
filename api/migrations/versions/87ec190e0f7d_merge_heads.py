"""merge heads

Revision ID: 87ec190e0f7d
Revises: 82b57eb2e598, 279fe9c09e38
Create Date: 2026-09-02 00:42:00

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "87ec190e0f7d"
down_revision: str | Sequence[str] | None = ("82b57eb2e598", "279fe9c09e38")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
