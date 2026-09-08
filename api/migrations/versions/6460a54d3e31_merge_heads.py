"""merge heads

Revision ID: 6460a54d3e31
Revises: a4b5c6d7e8f9, c4e7a1b93f26
Create Date: 2026-09-07 11:51:13.927454

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6460a54d3e31"
down_revision: str | Sequence[str] | None = ("a4b5c6d7e8f9", "c4e7a1b93f26")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
