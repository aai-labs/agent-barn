"""merge heads

Revision ID: da8ba7aeb850
Revises: 69011ec264e7, 6c3f9a2e8b41
Create Date: 2026-10-07 11:36:18.331060

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "da8ba7aeb850"
down_revision: str | Sequence[str] | None = ("69011ec264e7", "6c3f9a2e8b41")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
