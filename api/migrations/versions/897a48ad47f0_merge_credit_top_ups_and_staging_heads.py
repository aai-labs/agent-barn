"""Merge credit top-ups and staging heads.

Revision ID: 897a48ad47f0
Revises: d4a7c2e9f150, 877273bff59e
Create Date: 2026-10-19 11:05:24.162265

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "897a48ad47f0"
down_revision: str | Sequence[str] | None = ("d4a7c2e9f150", "877273bff59e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
