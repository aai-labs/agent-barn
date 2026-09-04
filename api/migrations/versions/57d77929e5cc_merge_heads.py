"""merge heads

Revision ID: 57d77929e5cc
Revises: 279fe9c09e38, c5617d35cbb2
Create Date: 2026-09-01 10:03:44.931661

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "57d77929e5cc"
down_revision: str | Sequence[str] | None = ("279fe9c09e38", "c5617d35cbb2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
