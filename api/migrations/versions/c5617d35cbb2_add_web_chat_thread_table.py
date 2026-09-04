"""add web_chat_thread table

Revision ID: c5617d35cbb2
Revises: af0a523a3dd6
Create Date: 2026-09-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5617d35cbb2"
down_revision: str | None = "af0a523a3dd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_chat_thread",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", sa.String(length=512), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "channel_id",
            "thread_id",
            name="uq_web_chat_thread_connection_channel_thread",
        ),
    )
    op.create_index(
        "ix_web_chat_thread_connection_channel",
        "web_chat_thread",
        ["connection_id", "channel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_web_chat_thread_connection_channel", table_name="web_chat_thread")
    op.drop_table("web_chat_thread")
