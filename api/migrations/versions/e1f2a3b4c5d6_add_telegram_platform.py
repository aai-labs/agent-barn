"""add telegram platform

Revision ID: e1f2a3b4c5d6
Revises: d3f9a1c7b2e5
Create Date: 2026-07-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d3f9a1c7b2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update the platform check constraint to include 'telegram'
    op.drop_constraint("ck_agent_platform", "agent", type_="check")
    op.create_check_constraint(
        "ck_agent_platform",
        "agent",
        "platform IN ('slack', 'teams', 'telegram')",
    )

    # 2. Create agent_telegram_config table
    op.create_table(
        "agent_telegram_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("bot_username", sa.String(length=255), nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allowed_chat_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("group_policy", sa.String(), nullable=False, server_default="allowlist"),
        sa.Column("dm_policy", sa.String(), nullable=False, server_default="off"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_telegram_config_agent_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_telegram_config")

    op.drop_constraint("ck_agent_platform", "agent", type_="check")
    op.create_check_constraint(
        "ck_agent_platform",
        "agent",
        "platform IN ('slack', 'teams')",
    )
