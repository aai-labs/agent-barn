"""merge heads

Revision ID: 50400a4c8a00
Revises: 6460a54d3e31, a2b3c4d5e6f7
Create Date: 2026-09-07 14:55:38.902821

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "50400a4c8a00"
down_revision: str | Sequence[str] | None = ("6460a54d3e31", "a2b3c4d5e6f7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
