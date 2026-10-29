"""Merge credit top-ups and staging merge heads.

Revision ID: 0fc7f5e68d9d
Revises: effd26cf62fa, 517d402a59fd
Create Date: 2026-10-20 10:47:48.489873

Both join staging's playbooks and Gmail app password heads; this joins the two joins.

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0fc7f5e68d9d"
down_revision: str | Sequence[str] | None = ("effd26cf62fa", "517d402a59fd")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
