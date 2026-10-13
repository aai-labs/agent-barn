"""Default the retired driver key so future writers can omit its column.

Revision ID: 8b1d5e7f9a23
Revises: 72c4a9e1b6d8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b1d5e7f9a23"
down_revision: str | Sequence[str] | None = "72c4a9e1b6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "communication_connection",
        "driver_key_encrypted",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=sa.text("''"),
    )


def downgrade() -> None:
    op.alter_column(
        "communication_connection",
        "driver_key_encrypted",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=None,
    )
