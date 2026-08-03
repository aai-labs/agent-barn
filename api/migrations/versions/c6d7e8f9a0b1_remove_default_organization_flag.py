"""remove default organization flag

Revision ID: c6d7e8f9a0b1
Revises: a7b8c9d0e1f2
Create Date: 2026-07-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("organization", "is_default")


def downgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
