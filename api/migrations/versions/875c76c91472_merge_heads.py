"""Join staging's file sync history with the skip-backup restore point column.

Revision ID: 875c76c91472
Revises: 921deb774e01, c3d7e9a1f5b8
Create Date: 2026-11-03 11:32:57.456095

No schema or data operations: preserves both independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "875c76c91472"
down_revision: str | tuple[str, ...] | None = ("921deb774e01", "c3d7e9a1f5b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
