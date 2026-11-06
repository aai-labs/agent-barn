"""Join AF-406's staging merge with the restore point changed file counts.

Revision ID: 91d534425109
Revises: 4621ebf7a53e, 8946864ecb73
Create Date: 2026-11-04 12:00:00.000000

No schema or data operations: preserves both independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "91d534425109"
down_revision: str | tuple[str, ...] | None = ("4621ebf7a53e", "8946864ecb73")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
