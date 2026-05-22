"""add slack settings to agent

Revision ID: a1b2c3d4e5f6
Revises: f2c8a14e9b37
Create Date: 2026-05-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f2c8a14e9b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("slack_channel_ids", sa.JSON(), nullable=True, server_default="[]"),
    )
    op.add_column(
        "agent",
        sa.Column("slack_dm_user_ids", sa.JSON(), nullable=True, server_default="[]"),
    )
    op.add_column(
        "agent",
        sa.Column(
            "slack_group_policy", sa.String(), nullable=True, server_default="open"
        ),
    )
    op.add_column(
        "agent",
        sa.Column("slack_dm_policy", sa.String(), nullable=True, server_default="open"),
    )


def downgrade() -> None:
    op.drop_column("agent", "slack_dm_policy")
    op.drop_column("agent", "slack_group_policy")
    op.drop_column("agent", "slack_dm_user_ids")
    op.drop_column("agent", "slack_channel_ids")
