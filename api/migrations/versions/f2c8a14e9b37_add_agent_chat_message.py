"""add agent_chat_message table

Revision ID: f2c8a14e9b37
Revises: f0c9d4a5e1b2
Create Date: 2026-05-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2c8a14e9b37"
down_revision: Union[str, None] = "f0c9d4a5e1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

message_direction_enum = postgresql.ENUM("INBOUND", "OUTBOUND", name="messagedirection", create_type=False)


def upgrade() -> None:
    message_direction_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_chat_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("openclaw_msg_id", sa.Text(), nullable=False),
        sa.Column("session_key", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("channel_name", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column(
            "direction",
            postgresql.ENUM("INBOUND", "OUTBOUND", name="messagedirection", create_type=False),
            nullable=False,
        ),
        sa.Column("sender_id", sa.Text(), nullable=True),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "openclaw_msg_id", name="uq_agent_chat_message_agent_msg"),
    )
    op.create_index(
        "ix_agent_chat_message_agent_channel",
        "agent_chat_message",
        ["agent_id", "channel_id"],
    )
    op.create_index(
        "ix_agent_chat_message_agent_session",
        "agent_chat_message",
        ["agent_id", "session_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_message_agent_session", table_name="agent_chat_message")
    op.drop_index("ix_agent_chat_message_agent_channel", table_name="agent_chat_message")
    op.drop_table("agent_chat_message")
    message_direction_enum.drop(op.get_bind(), checkfirst=True)
