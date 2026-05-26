"""add tool_call tables

Revision ID: f0c9d4a5e1b2
Revises: e9b4f23c5a71
Create Date: 2026-05-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f0c9d4a5e1b2"
down_revision: Union[str, None] = "e9b4f23c5a71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tool_call_status_enum = postgresql.ENUM(
    "PENDING", "SUCCESS", "ERROR", name="toolcallstatus", create_type=False
)


def upgrade() -> None:
    tool_call_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tool_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", tool_call_status_enum, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "external_id", name="uq_tool_call_agent_external"
        ),
    )
    op.create_index(
        "ix_tool_call_agent_occurred", "tool_call", ["agent_id", "occurred_at"]
    )
    op.create_index("ix_tool_call_agent_tool", "tool_call", ["agent_id", "tool_name"])

    op.create_table(
        "tool_call_sync_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_file_path", sa.Text(), nullable=False),
        sa.Column("last_byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "session_file_path", name="uq_tcss_agent_file"),
    )


def downgrade() -> None:
    op.drop_table("tool_call_sync_state")
    op.drop_index("ix_tool_call_agent_tool", table_name="tool_call")
    op.drop_index("ix_tool_call_agent_occurred", table_name="tool_call")
    op.drop_table("tool_call")
    tool_call_status_enum.drop(op.get_bind(), checkfirst=True)
