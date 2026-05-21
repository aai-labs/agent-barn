"""add sender_name to agent_chat_message

Revision ID: d7a3b91c4e05
Revises: c9d4e81f3a02
Create Date: 2026-05-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3b91c4e05"
down_revision: Union[str, None] = "c9d4e81f3a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_chat_message",
        sa.Column("sender_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_chat_message", "sender_name")
