"""merge heads

Revision ID: 71a0d9a1a91d
Revises: d731eac8a160, ee8815d37c1c
Create Date: 2026-08-05 07:48:09.783509

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "71a0d9a1a91d"
down_revision: str | Sequence[str] | None = ("d731eac8a160", "ee8815d37c1c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
