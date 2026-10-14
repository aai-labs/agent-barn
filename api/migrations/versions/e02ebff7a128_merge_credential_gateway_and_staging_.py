"""Merge credential gateway and staging migration heads

Revision ID: e02ebff7a128
Revises: aaf767b06036, ce9b52ee0b2b
Create Date: 2026-10-08 12:36:28.029294

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e02ebff7a128"
down_revision: str | Sequence[str] | None = ("aaf767b06036", "ce9b52ee0b2b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
