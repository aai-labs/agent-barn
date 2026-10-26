"""restore point backup skipped by user

Revision ID: c7d2e9f4a1b3
Revises: 8b2e4f61c9d3
Create Date: 2026-10-21 12:00:00.000000

Whether the restore running from a restore point was one the user chose to run without
a backup (AF-406). It was a label on the restore Job, which a reaped Job takes with it.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d2e9f4a1b3"
down_revision: str | Sequence[str] | None = "8b2e4f61c9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_restore_point",
        sa.Column("backup_skipped_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_restore_point", "backup_skipped_by_user")
