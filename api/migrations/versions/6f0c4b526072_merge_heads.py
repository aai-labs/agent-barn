"""merge heads

Revision ID: 6f0c4b526072
Revises: c4e8a2f19d73, c8e3a5b71d94
Create Date: 2026-09-15 13:22:06.058634

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6f0c4b526072"
down_revision: str | Sequence[str] | None = ("c4e8a2f19d73", "c8e3a5b71d94")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
