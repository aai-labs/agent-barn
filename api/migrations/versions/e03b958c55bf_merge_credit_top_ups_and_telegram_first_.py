"""Merge credit top-ups and Telegram first message heads.

Revision ID: e03b958c55bf
Revises: 6553916224ec, a78bcde4b918
Create Date: 2026-10-19 17:27:40.956117

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e03b958c55bf"
down_revision: str | Sequence[str] | None = ("6553916224ec", "a78bcde4b918")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
