"""merge heads

Revision ID: ce9b52ee0b2b
Revises: 50400a4c8a00, c9bf0b2f5ff1
Create Date: 2026-09-07 18:07:34.786464

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ce9b52ee0b2b"
down_revision: str | Sequence[str] | None = ("50400a4c8a00", "c9bf0b2f5ff1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
