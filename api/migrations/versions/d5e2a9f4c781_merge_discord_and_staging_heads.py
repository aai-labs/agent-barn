"""merge Discord and staging heads

Revision ID: d5e2a9f4c781
Revises: 8a7b6c5d4e3f, c4d1e8f2a730
Create Date: 2026-08-17

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d5e2a9f4c781"
down_revision: str | Sequence[str] | None = ("8a7b6c5d4e3f", "c4d1e8f2a730")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
