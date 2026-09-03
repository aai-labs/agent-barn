"""add safe structured communication error details

Revision ID: 8c4d2e7f9a10
Revises: f4a9c2d7e1b6
Create Date: 2026-08-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c4d2e7f9a10"
down_revision: str | Sequence[str] | None = "f4a9c2d7e1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communication_connection",
        sa.Column("last_error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "communication_operation_journal",
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_operation_journal", "error_details")
    op.drop_column("communication_connection", "last_error_details")
