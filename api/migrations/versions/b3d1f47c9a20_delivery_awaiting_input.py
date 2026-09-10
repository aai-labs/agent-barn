"""delivery awaiting input

Revision ID: b3d1f47c9a20
Revises: c92d0eaf3101
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d1f47c9a20"
down_revision: str | Sequence[str] | None = "c92d0eaf3101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communication_delivery",
        sa.Column("awaiting_input", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("communication_delivery", "awaiting_input")
