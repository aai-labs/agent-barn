"""Merge OneDrive sync connection and trial onboarding heads.

Revision ID: 0219de43e2c9
Revises: 734b0f2b3793, b3d8e1f4a6c2
Create Date: 2026-10-14 16:32:12.444434

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0219de43e2c9"
down_revision: str | Sequence[str] | None = ("734b0f2b3793", "b3d8e1f4a6c2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
