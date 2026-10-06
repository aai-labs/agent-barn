"""agentbarn telegram intake

Revision ID: fcdc690dbf31
Revises: e91e4d921140
Create Date: 2026-10-06 16:00:00.000000

The lease that lets exactly one Communications replica poll Agent Barn's shared
Telegram bot, and the durable intake of the updates it receives. Both are new,
so there is no data to migrate.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fcdc690dbf31"
down_revision: str | Sequence[str] | None = "e91e4d921140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = sa.Enum("RECEIVED", "QUEUED", "HANDLED", "FORWARDED", "DROPPED", name="agentbarntelegramupdatestatus")


def upgrade() -> None:
    op.create_table(
        "agentbarn_telegram_ingress_lease",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "agentbarn_telegram_update",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("status", _STATUS, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("update_id", name="uq_agentbarn_telegram_update_update_id"),
    )
    op.create_index("ix_agentbarn_telegram_update_status", "agentbarn_telegram_update", ["status", "update_id"])
    op.create_index("ix_agentbarn_telegram_update_agent", "agentbarn_telegram_update", ["agent_id"])
    op.create_index(
        "ix_agentbarn_telegram_update_user_queue", "agentbarn_telegram_update", ["telegram_user_id", "update_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agentbarn_telegram_update_user_queue", table_name="agentbarn_telegram_update")
    op.drop_index("ix_agentbarn_telegram_update_agent", table_name="agentbarn_telegram_update")
    op.drop_index("ix_agentbarn_telegram_update_status", table_name="agentbarn_telegram_update")
    op.drop_table("agentbarn_telegram_update")
    op.drop_table("agentbarn_telegram_ingress_lease")
    _STATUS.drop(op.get_bind(), checkfirst=True)
