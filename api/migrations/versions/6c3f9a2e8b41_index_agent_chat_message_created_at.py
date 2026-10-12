"""Index agent_chat_message by created_at for hourly message counts.

Revision ID: 6c3f9a2e8b41
Revises: 5a1e7c3b9d20
"""

from alembic import op

revision = "6c3f9a2e8b41"
down_revision = "5a1e7c3b9d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_agent_chat_message_created_at", "agent_chat_message", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_chat_message_created_at", table_name="agent_chat_message")
