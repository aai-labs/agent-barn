"""remove legacy single-platform agent architecture

Revision ID: 8f5c1a6e4b93
Revises: 7e4b0f5d3a82
Create Date: 2026-08-22 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f5c1a6e4b93"
down_revision: str | Sequence[str] | None = "7e4b0f5d3a82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Messages produced by native runtime channel adapters have no generic
    # Connection identity and cannot satisfy the new canonical contract.
    op.execute("DELETE FROM agent_chat_message WHERE connection_id IS NULL")
    op.drop_index("uq_agent_chat_message_legacy_agent_msg", table_name="agent_chat_message")
    op.alter_column("agent_chat_message", "connection_id", nullable=False)

    op.drop_table("agent_slack_config")
    op.drop_table("agent_teams_config")
    op.drop_table("agent_telegram_config")
    op.drop_table("agent_discord_config")
    op.drop_table("user_slack_config_token")
    op.drop_column("agent", "platform")


def downgrade() -> None:
    op.create_table(
        "user_slack_config_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_token_encrypted", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_slack_config_token_user"),
    )
    op.add_column(
        "agent",
        sa.Column("platform", sa.String(length=10), server_default="slack", nullable=False),
    )
    op.create_check_constraint(
        "ck_agent_platform",
        "agent",
        "platform IN ('slack', 'teams', 'telegram', 'discord')",
    )
    op.create_table(
        "agent_slack_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("bot_token_encrypted", sa.String(), nullable=False),
        sa.Column("app_token_encrypted", sa.String(), nullable=False),
        sa.Column("bot_token_hash", sa.String(), nullable=True),
        sa.Column("channel_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("dm_user_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("group_policy", sa.String(), server_default="allowlist", nullable=False),
        sa.Column("dm_policy", sa.String(), server_default="off", nullable=False),
        sa.Column("verbose_mode", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index(
        "ix_agent_slack_config_bot_token_hash",
        "agent_slack_config",
        ["bot_token_hash"],
        unique=True,
        postgresql_where=sa.text("bot_token_hash IS NOT NULL"),
    )
    op.create_table(
        "agent_teams_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("app_id_encrypted", sa.String(), nullable=False),
        sa.Column("app_password_encrypted", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_table(
        "agent_telegram_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("bot_token_encrypted", sa.String(), nullable=False),
        sa.Column("bot_username", sa.String(length=255), nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("allowed_chat_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("group_policy", sa.String(), server_default="allowlist", nullable=False),
        sa.Column("dm_policy", sa.String(), server_default="off", nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_table(
        "agent_discord_config",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("bot_token_hash", sa.Text(), nullable=True),
        sa.Column("guild_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("allowed_channel_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("allowed_user_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("allowed_role_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("home_channel_id", sa.String(length=32), nullable=True),
        sa.Column("require_mention", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("group_policy", sa.String(), server_default="allowlist", nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_discord_config_agent_id"),
    )
    op.create_index(
        "ix_agent_discord_config_bot_token_hash",
        "agent_discord_config",
        ["bot_token_hash"],
        unique=True,
        postgresql_where=sa.text("bot_token_hash IS NOT NULL"),
    )
    op.alter_column("agent_chat_message", "connection_id", nullable=True)
    op.create_index(
        "uq_agent_chat_message_legacy_agent_msg",
        "agent_chat_message",
        ["agent_id", "openclaw_msg_id"],
        unique=True,
        postgresql_where=sa.text("connection_id IS NULL"),
    )
