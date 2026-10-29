"""merge heads

Revision ID: fa6ffd5fe1f2
Revises: 69011ec264e7, a309cd8a0ccc
Create Date: 2026-10-07 15:00:55.609980

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "fa6ffd5fe1f2"
down_revision: str | tuple[str, ...] | None = ("69011ec264e7", "a309cd8a0ccc")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
