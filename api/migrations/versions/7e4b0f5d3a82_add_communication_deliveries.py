"""add communication deliveries

Revision ID: 7e4b0f5d3a82
Revises: 6d3a9e4c2f71
Create Date: 2026-08-22 11:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7e4b0f5d3a82"
down_revision: str | Sequence[str] | None = "6d3a9e4c2f71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("communication_key_encrypted", sa.String(), nullable=True))
    op.drop_constraint("uq_agent_chat_message_agent_msg", "agent_chat_message", type_="unique")
    op.create_index(
        "uq_agent_chat_message_legacy_agent_msg",
        "agent_chat_message",
        ["agent_id", "openclaw_msg_id"],
        unique=True,
        postgresql_where=sa.text("connection_id IS NULL"),
    )
    op.create_index(
        "uq_agent_chat_message_connection_msg",
        "agent_chat_message",
        ["connection_id", "openclaw_msg_id"],
        unique=True,
        postgresql_where=sa.text("connection_id IS NOT NULL"),
    )
    op.create_table(
        "communication_delivery",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("ordering_key", sa.String(length=1024), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=512), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_communication_delivery_attempt_count"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "organization_id"],
            ["communication_connection.id", "communication_connection.organization_id"],
            name="fk_communication_delivery_connection_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["message_id"], ["agent_chat_message.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "direction",
            "idempotency_key",
            name="uq_communication_delivery_idempotency",
        ),
    )
    op.create_index("ix_communication_delivery_agent", "communication_delivery", ["agent_id"])
    op.create_index(
        "ix_communication_delivery_connection_status",
        "communication_delivery",
        ["connection_id", "status"],
    )
    op.create_index(
        "ix_communication_delivery_ordering",
        "communication_delivery",
        ["ordering_key", "created_at"],
    )
    op.create_index(
        "ix_communication_delivery_status_available",
        "communication_delivery",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_communication_delivery_status_available", table_name="communication_delivery")
    op.drop_index("ix_communication_delivery_ordering", table_name="communication_delivery")
    op.drop_index("ix_communication_delivery_connection_status", table_name="communication_delivery")
    op.drop_index("ix_communication_delivery_agent", table_name="communication_delivery")
    op.drop_table("communication_delivery")
    op.drop_index("uq_agent_chat_message_connection_msg", table_name="agent_chat_message")
    op.drop_index("uq_agent_chat_message_legacy_agent_msg", table_name="agent_chat_message")
    op.create_unique_constraint(
        "uq_agent_chat_message_agent_msg",
        "agent_chat_message",
        ["agent_id", "openclaw_msg_id"],
    )
    op.drop_column("agent", "communication_key_encrypted")
