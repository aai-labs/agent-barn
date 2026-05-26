"""add platform and config tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add platform column to agent
    op.add_column(
        "agent",
        sa.Column(
            "platform",
            sa.String(length=10),
            nullable=False,
            server_default="slack",
        ),
    )
    op.create_check_constraint(
        "ck_agent_platform",
        "agent",
        "platform IN ('slack', 'teams')",
    )

    # 2. Create agent_slack_config table
    op.create_table(
        "agent_slack_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("app_token_encrypted", sa.Text(), nullable=False),
        sa.Column("channel_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("dm_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "group_policy", sa.String(), nullable=False, server_default="allowlist"
        ),
        sa.Column("dm_policy", sa.String(), nullable=False, server_default="off"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_slack_config_agent_id"),
    )

    # 3. Migrate existing Slack data from agent → agent_slack_config
    op.execute(
        sa.text("""
            INSERT INTO agent_slack_config
                (id, created_at, updated_at, agent_id,
                 bot_token_encrypted, app_token_encrypted,
                 channel_ids, dm_user_ids, group_policy, dm_policy)
            SELECT
                gen_random_uuid(), now(), now(), id,
                slack_bot_token_encrypted, slack_app_token_encrypted,
                COALESCE(slack_channel_ids, '[]'::json),
                COALESCE(slack_dm_user_ids, '[]'::json),
                COALESCE(slack_group_policy, 'allowlist'),
                COALESCE(slack_dm_policy, 'off')
            FROM agent
        """)
    )

    # 4. Drop Slack columns from agent
    op.drop_column("agent", "slack_bot_token_encrypted")
    op.drop_column("agent", "slack_app_token_encrypted")
    op.drop_column("agent", "slack_channel_ids")
    op.drop_column("agent", "slack_dm_user_ids")
    op.drop_column("agent", "slack_group_policy")
    op.drop_column("agent", "slack_dm_policy")

    # 5. Create agent_teams_config table
    op.create_table(
        "agent_teams_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("app_id_encrypted", sa.Text(), nullable=False),
        sa.Column("app_password_encrypted", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_teams_config_agent_id"),
    )


def downgrade() -> None:
    # Drop teams config
    op.drop_table("agent_teams_config")

    # Re-add Slack columns to agent
    op.add_column(
        "agent",
        sa.Column(
            "slack_bot_token_encrypted", sa.Text(), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "agent",
        sa.Column(
            "slack_app_token_encrypted", sa.Text(), nullable=False, server_default=""
        ),
    )
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
            "slack_group_policy", sa.String(), nullable=True, server_default="allowlist"
        ),
    )
    op.add_column(
        "agent",
        sa.Column("slack_dm_policy", sa.String(), nullable=True, server_default="off"),
    )

    # Migrate data back from agent_slack_config → agent
    op.execute(
        sa.text("""
            UPDATE agent SET
                slack_bot_token_encrypted = asc.bot_token_encrypted,
                slack_app_token_encrypted = asc.app_token_encrypted,
                slack_channel_ids = asc.channel_ids,
                slack_dm_user_ids = asc.dm_user_ids,
                slack_group_policy = asc.group_policy,
                slack_dm_policy = asc.dm_policy
            FROM agent_slack_config asc
            WHERE agent.id = asc.agent_id
        """)
    )

    # Drop slack config table
    op.drop_table("agent_slack_config")

    # Drop platform column
    op.drop_constraint("ck_agent_platform", "agent", type_="check")
    op.drop_column("agent", "platform")
