"""Merge agent tasks and agent sizes heads.

Revision ID: 3fb664907ef8
Revises: d2f8a6c41e07, 8b2e4f61c9d3
Create Date: 2026-10-27 09:55:05.246180

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "3fb664907ef8"
down_revision: str | Sequence[str] | None = ("d2f8a6c41e07", "8b2e4f61c9d3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
