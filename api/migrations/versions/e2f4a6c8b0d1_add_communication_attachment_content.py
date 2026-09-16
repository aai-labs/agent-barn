"""add communication attachment content

Revision ID: e2f4a6c8b0d1
Revises: c4e8a2f19d73
Create Date: 2026-09-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlmodel.sql.sqltypes import AutoString

revision: str = "e2f4a6c8b0d1"
down_revision: str | None = "c4e8a2f19d73"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "communication_attachment_content",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("outbound_delivery_id", sa.Uuid(), nullable=True),
        sa.Column("pending_provider_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_attachment_id", AutoString(length=512), nullable=True),
        sa.Column("idempotency_key", AutoString(length=512), nullable=False),
        sa.Column("media_type", AutoString(length=255), nullable=False),
        sa.Column("filename", AutoString(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["outbound_delivery_id"],
            ["communication_delivery.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "idempotency_key", name="uq_attachment_content_agent_idempotency"),
    )
    op.create_index(
        "ix_communication_attachment_content_agent_id",
        "communication_attachment_content",
        ["agent_id"],
    )
    op.create_index(
        "ix_communication_attachment_content_created",
        "communication_attachment_content",
        ["created_at"],
    )
    op.create_index(
        "ix_communication_attachment_content_outbound_delivery_id",
        "communication_attachment_content",
        ["outbound_delivery_id"],
    )
    op.create_index(
        "ix_communication_attachment_content_pending_provider_consent",
        "communication_attachment_content",
        ["pending_provider_consent"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_attachment_content_pending_provider_consent",
        table_name="communication_attachment_content",
    )
    op.drop_index(
        "ix_communication_attachment_content_outbound_delivery_id",
        table_name="communication_attachment_content",
    )
    op.drop_index("ix_communication_attachment_content_created", table_name="communication_attachment_content")
    op.drop_index("ix_communication_attachment_content_agent_id", table_name="communication_attachment_content")
    op.drop_table("communication_attachment_content")
