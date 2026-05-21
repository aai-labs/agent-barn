"""add channel_name to agent_chat_message

Revision ID: c9d4e81f3a02
Revises: f2c8a14e9b37
Create Date: 2026-05-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d4e81f3a02"
down_revision: Union[str, None] = "f2c8a14e9b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_chat_message",
        sa.Column("channel_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_chat_message", "channel_name")
