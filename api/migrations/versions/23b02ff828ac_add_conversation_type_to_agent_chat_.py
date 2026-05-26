"""add conversation_type to agent_chat_message

Revision ID: 23b02ff828ac
Revises: f2c8a14e9b37
Create Date: 2026-05-25 12:26:37.122964

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "23b02ff828ac"
down_revision: Union[str, None] = "f2c8a14e9b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sa.Enum("CHANNEL", "DM", name="conversationtype").create(op.get_bind())
    op.add_column(
        "agent_chat_message",
        sa.Column(
            "conversation_type",
            postgresql.ENUM(
                "CHANNEL", "DM", name="conversationtype", create_type=False
            ),
            server_default="CHANNEL",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_chat_message", "conversation_type")
    sa.Enum("CHANNEL", "DM", name="conversationtype").drop(op.get_bind())
