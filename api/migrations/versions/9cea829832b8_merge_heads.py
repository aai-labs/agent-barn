"""Join AF-406's staging merge with the scheduled restore point origin.

Revision ID: 9cea829832b8
Revises: 875c76c91472, f2b7d9c4a6e1
Create Date: 2026-11-03 13:05:18.000000

No schema or data operations: preserves both independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9cea829832b8"
down_revision: str | tuple[str, ...] | None = ("875c76c91472", "f2b7d9c4a6e1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
