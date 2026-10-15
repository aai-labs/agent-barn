"""agentbarn telegram message ownership

Revision ID: dfcfdf34eefa
Revises: 164fb0fb6c2c
Create Date: 2026-10-12 15:30:00.000000

Which Connection each shared-bot message and file id belongs to, so an Agent can
act only on its own part of a chat that a Telegram user keeps across Agents. The
tables are new, so there is no data to migrate.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dfcfdf34eefa"
down_revision: str | Sequence[str] | None = "164fb0fb6c2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agentbarn_telegram_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_agentbarn_telegram_message_chat_message"),
    )
    op.create_index("ix_agentbarn_telegram_message_connection", "agentbarn_telegram_message", ["connection_id"])
    op.create_table(
        "agentbarn_telegram_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("connection_id", "file_id", name="uq_agentbarn_telegram_file_connection_file"),
    )


def downgrade() -> None:
    op.drop_table("agentbarn_telegram_file")
    op.drop_index("ix_agentbarn_telegram_message_connection", table_name="agentbarn_telegram_message")
    op.drop_table("agentbarn_telegram_message")
