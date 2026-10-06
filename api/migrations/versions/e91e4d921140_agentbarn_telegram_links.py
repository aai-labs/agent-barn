"""agentbarn telegram links

Revision ID: e91e4d921140
Revises: d7aaf4231438
Create Date: 2026-10-06 14:00:00.000000

Telegram users linked to an Agent through Agent Barn's shared bot, and the
one-time tokens Members open in Telegram to create those links. Both are new,
so there is no data to migrate.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e91e4d921140"
down_revision: str | Sequence[str] | None = "d7aaf4231438"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agentbarn_telegram_link",
        *_timestamps(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "organization_id"],
            ["communication_connection.id", "communication_connection.organization_id"],
            name="fk_agentbarn_telegram_link_connection_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_membership_id", "organization_id"],
            ["user_organization.id", "user_organization.organization_id"],
            name="fk_agentbarn_telegram_link_membership_organization",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_agentbarn_telegram_link_active_user",
        "agentbarn_telegram_link",
        ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )
    op.create_index("ix_agentbarn_telegram_link_connection", "agentbarn_telegram_link", ["connection_id"])
    op.create_index("ix_agentbarn_telegram_link_agent", "agentbarn_telegram_link", ["agent_id"])

    op.create_table(
        "agentbarn_telegram_link_token",
        *_timestamps(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("link_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_agentbarn_telegram_link_token_hash"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["link_id"], ["agentbarn_telegram_link.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["connection_id", "organization_id"],
            ["communication_connection.id", "communication_connection.organization_id"],
            name="fk_agentbarn_telegram_link_token_connection_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "organization_id"],
            ["user_organization.id", "user_organization.organization_id"],
            name="fk_agentbarn_telegram_link_token_membership_organization",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_agentbarn_telegram_link_token_connection", "agentbarn_telegram_link_token", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_agentbarn_telegram_link_token_connection", table_name="agentbarn_telegram_link_token")
    op.drop_table("agentbarn_telegram_link_token")
    op.drop_index("ix_agentbarn_telegram_link_agent", table_name="agentbarn_telegram_link")
    op.drop_index("ix_agentbarn_telegram_link_connection", table_name="agentbarn_telegram_link")
    op.drop_index("uq_agentbarn_telegram_link_active_user", table_name="agentbarn_telegram_link")
    op.drop_table("agentbarn_telegram_link")
