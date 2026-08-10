"""merge heads

Revision ID: 1aa6ed23c288
Revises: 6c23680e1076, ee8815d37c1c
Create Date: 2026-08-05 04:59:31.536928

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "1aa6ed23c288"
down_revision: str | Sequence[str] | None = ("6c23680e1076", "ee8815d37c1c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
