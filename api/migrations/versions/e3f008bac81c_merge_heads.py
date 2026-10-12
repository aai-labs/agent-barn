"""Merge the trial onboarding history with staging's managed update merge.

Revision ID: e3f008bac81c
Revises: b3d8e1f4a6c2, f1aac76e927a
"""

from collections.abc import Sequence

revision: str = "e3f008bac81c"
down_revision: str | Sequence[str] | None = ("b3d8e1f4a6c2", "f1aac76e927a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
