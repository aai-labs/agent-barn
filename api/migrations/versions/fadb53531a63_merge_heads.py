"""merge heads

Revision ID: fadb53531a63
Revises: 5e0adff0f5e2, f6a7b8c9d0e1
Create Date: 2026-08-07 10:27:44.196577

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "fadb53531a63"
down_revision: str | Sequence[str] | None = ("5e0adff0f5e2", "f6a7b8c9d0e1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
