"""merge heads

Revision ID: 2b89b1023b35
Revises: 50400a4c8a00, d5a48a7fe943
Create Date: 2026-09-08 11:00:36.305445

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "2b89b1023b35"
down_revision: str | Sequence[str] | None = ("50400a4c8a00", "d5a48a7fe943")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
