"""enforce one active built-in Web Chat Connection per Agent

Revision ID: 4fb2ac67de91
Revises: 57d77929e5cc
Create Date: 2026-09-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4fb2ac67de91"
down_revision: str | Sequence[str] | None = "57d77929e5cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_communication_connection_active_web",
        "communication_connection",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND platform_key = 'web'"),
    )


def downgrade() -> None:
    op.drop_index("uq_communication_connection_active_web", table_name="communication_connection")
