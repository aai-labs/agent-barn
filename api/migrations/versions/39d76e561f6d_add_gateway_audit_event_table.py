"""add gateway audit event table

Revision ID: 39d76e561f6d
Revises: a85f48650d6a
Create Date: 2026-09-05

A durable row per gateway resolution/lifecycle event, written by the same Postgres the
resolution hot path already depends on. No foreign keys on agent_id/organization_id:
audit evidence must survive later deletion of the Agent or org it names.
"""

import sqlalchemy as sa
from alembic import op

revision = "39d76e561f6d"
down_revision = "a85f48650d6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_audit_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gateway_audit_event_organization", "gateway_audit_event", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_gateway_audit_event_organization", table_name="gateway_audit_event")
    op.drop_table("gateway_audit_event")
