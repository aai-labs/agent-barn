"""one telegram connection per agent

Revision ID: d7aaf4231438
Revises: aaf767b06036
Create Date: 2026-10-06 12:00:00.000000

An Agent runs a single Telegram adapter, so it may hold either a bring-your-own
`telegram` Connection or an `agentbarn_telegram` one, never both. Existing data
already satisfies this: `agentbarn_telegram` Connections do not exist yet and
`uq_communication_connection_active_platform` already limits `telegram` to one.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7aaf4231438"
down_revision: str | Sequence[str] | None = "aaf767b06036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_communication_connection_active_telegram",
        "communication_connection",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND platform_key IN ('telegram', 'agentbarn_telegram')"),
    )


def downgrade() -> None:
    op.drop_index("uq_communication_connection_active_telegram", table_name="communication_connection")
