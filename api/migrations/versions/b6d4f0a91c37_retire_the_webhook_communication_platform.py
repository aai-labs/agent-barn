"""retire the webhook Communication Platform

Revision ID: b6d4f0a91c37
Revises: 7a9c2e4f6b81
Create Date: 2026-09-22 00:00:00.000000

Agent Webhooks replaced the webhook Platform, so its Connections, deliveries, and
transcript rows are removed together with the columns only that Platform used. The
Platform never reached a release, so the data exists on staging only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d4f0a91c37"
down_revision: str | Sequence[str] | None = "7a9c2e4f6b81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Children first: every reference to a Connection is ON DELETE RESTRICT.
    for table in ("communication_operation_journal", "communication_delivery", "agent_chat_message"):
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE connection_id IN "
                "(SELECT id FROM communication_connection WHERE platform_key = 'webhook')"
            )
        )
    op.execute(sa.text("DELETE FROM communication_connection WHERE platform_key = 'webhook'"))

    op.drop_column("communication_delivery", "session_key")
    op.drop_column("communication_delivery", "kind")

    op.drop_index("uq_communication_connection_active_singleton", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_platform",
        "communication_connection",
        ["agent_id", "platform_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.drop_column("communication_connection", "singleton_key")
    # PostgreSQL has no DROP VALUE, so 'EVENT' stays unused on conversationtype.


def downgrade() -> None:
    # The removed webhook data is not restored; only the schema is.
    op.add_column(
        "communication_connection",
        sa.Column("singleton_key", sa.String(length=64), nullable=True),
    )
    op.execute(sa.text("UPDATE communication_connection SET singleton_key = platform_key"))
    op.drop_index("uq_communication_connection_active_platform", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_singleton",
        "communication_connection",
        ["agent_id", "singleton_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.add_column(
        "communication_delivery",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="CONVERSATION"),
    )
    op.add_column(
        "communication_delivery",
        sa.Column("session_key", sa.String(length=1024), nullable=True),
    )
