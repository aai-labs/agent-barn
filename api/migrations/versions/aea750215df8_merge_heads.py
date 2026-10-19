"""Merge Agent Barn Telegram and retired Skill provider cleanup heads.

Revision ID: aea750215df8
Revises: 85f51aa260cb, c42e91b7a603
Create Date: 2026-10-13 13:07:16.970874

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "aea750215df8"
down_revision: str | Sequence[str] | None = ("85f51aa260cb", "c42e91b7a603")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
