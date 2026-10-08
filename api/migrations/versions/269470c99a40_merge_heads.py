"""merge heads

Revision ID: 269470c99a40
Revises: 43eefac934c1, a0e8c15d9e34
Create Date: 2026-09-18 05:56:42.706883

"""

from collections.abc import Sequence

revision: str = "269470c99a40"
down_revision: str | Sequence[str] | None = ("43eefac934c1", "a0e8c15d9e34")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
