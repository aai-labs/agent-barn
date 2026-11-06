"""Join staging's restore point history with the Discord require-mention retirement.

Revision ID: 6409cd279f40
Revises: 91d534425109, e450d5774324
Create Date: 2026-11-06 09:41:54.237657

No schema or data operations: preserves both independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6409cd279f40"
down_revision: str | tuple[str, ...] | None = ("91d534425109", "e450d5774324")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
