"""add normalized agent provisioning error fields

Revision ID: c8e3a5b71d94
Revises: b3d1f47c9a20
Create Date: 2026-09-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e3a5b71d94"
down_revision: str | Sequence[str] | None = "b3d1f47c9a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing `agent.last_error` rows keep their unsanitized text and get no code.
    # The read boundary reports a row with no code as an unclassified failure and
    # drops its text, so no backfill is needed.
    op.add_column("agent", sa.Column("last_error_code", sa.String(length=100), nullable=True))
    op.add_column("agent", sa.Column("last_error_detail", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "last_error_detail")
    op.drop_column("agent", "last_error_code")
