"""add Discord platform configuration

Revision ID: 8a7b6c5d4e3f
Revises: 3df7fef61316
Create Date: 2026-08-13

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8a7b6c5d4e3f"
down_revision: str | None = "3df7fef61316"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_agent_platform", "agent", type_="check")
    op.create_check_constraint("ck_agent_platform", "agent", "platform IN ('slack', 'teams', 'telegram', 'discord')")
    op.create_table(
        "agent_discord_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("bot_token_hash", sa.Text(), nullable=True),
        sa.Column("guild_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allowed_channel_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allowed_role_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("home_channel_id", sa.String(length=32), nullable=True),
        sa.Column("require_mention", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("group_policy", sa.String(), nullable=False, server_default="allowlist"),
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


def downgrade() -> None:
    op.drop_table("agent_discord_config")
    op.drop_constraint("ck_agent_platform", "agent", type_="check")
    op.create_check_constraint("ck_agent_platform", "agent", "platform IN ('slack', 'teams', 'telegram')")
