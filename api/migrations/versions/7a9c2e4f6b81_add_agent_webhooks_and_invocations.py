"""add Agent Webhooks and Webhook Invocations

Revision ID: 7a9c2e4f6b81
Revises: 4b4bb4af4d31
Create Date: 2026-09-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a9c2e4f6b81"
down_revision: str | Sequence[str] | None = "4b4bb4af4d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_webhook",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("delivery_platform", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_agent_webhook_revision"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_webhook_agent_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_webhook_id_organization"),
    )
    op.create_index("ix_agent_webhook_agent", "agent_webhook", ["agent_id"], unique=False)
    op.create_index("ix_agent_webhook_organization", "agent_webhook", ["organization_id"], unique=False)
    op.create_index(
        "uq_agent_webhook_active_name",
        "agent_webhook",
        ["agent_id", sa.literal_column("lower(display_name)")],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    op.create_table(
        "webhook_invocation",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("webhook_id", sa.Uuid(), nullable=False),
        sa.Column("external_event_id", sa.String(length=512), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="RECEIVED", nullable=False),
        sa.Column("dispatch_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("native_job_id", sa.String(length=255), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dispatch_attempt_count >= 0", name="ck_webhook_invocation_dispatch_attempt_count"),
        sa.CheckConstraint("dispatch_generation > 0", name="ck_webhook_invocation_dispatch_generation"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_webhook_invocation_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id", "organization_id"],
            ["agent_webhook.id", "agent_webhook.organization_id"],
            name="fk_webhook_invocation_webhook_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        # NULL event ids are distinct in PostgreSQL, so only caller-supplied ids deduplicate.
        sa.UniqueConstraint("webhook_id", "external_event_id", name="uq_webhook_invocation_external_event"),
    )
    op.create_index("ix_webhook_invocation_agent_status", "webhook_invocation", ["agent_id", "status"], unique=False)
    op.create_index(
        "ix_webhook_invocation_webhook_created",
        "webhook_invocation",
        ["webhook_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_invocation_webhook_created", table_name="webhook_invocation")
    op.drop_index("ix_webhook_invocation_agent_status", table_name="webhook_invocation")
    op.drop_table("webhook_invocation")
    op.drop_index("uq_agent_webhook_active_name", table_name="agent_webhook")
    op.drop_index("ix_agent_webhook_organization", table_name="agent_webhook")
    op.drop_index("ix_agent_webhook_agent", table_name="agent_webhook")
    op.drop_table("agent_webhook")
