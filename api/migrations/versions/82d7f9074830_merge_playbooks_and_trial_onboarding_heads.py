"""Merge Playbooks and trial onboarding heads.

Revision ID: 82d7f9074830
Revises: b3d8e1f4a6c2, cd4c6b9354f9
Create Date: 2026-10-14

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "82d7f9074830"
down_revision: str | Sequence[str] | None = ("b3d8e1f4a6c2", "cd4c6b9354f9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
