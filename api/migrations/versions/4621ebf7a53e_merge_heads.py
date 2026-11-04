"""Join staging's locked sync items with AF-406's restore point history.

Revision ID: 4621ebf7a53e
Revises: 3680352c132d, 875c76c91472
Create Date: 2026-11-04 12:00:00.000000

No schema or data operations: preserves both independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4621ebf7a53e"
down_revision: str | tuple[str, ...] | None = ("3680352c132d", "875c76c91472")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
