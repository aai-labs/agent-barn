"""add gateway token table

Revision ID: c50f6d65b1b7
Revises: 87ec190e0f7d
Create Date: 2026-09-02

A Gateway Token identifies one (Agent, provider) pair to the credential gateway. It is a
credential to Agent Barn, not to a provider, and is stored as a SHA-256 hash because the
gateway resolves a presented bearer token by lookup and never needs the plaintext back.
"""

import sqlalchemy as sa
from alembic import op

revision = "c50f6d65b1b7"
down_revision = "87ec190e0f7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        # Composite FK against agent's (id, organization_id) unique constraint keeps the
        # denormalized organization_id from drifting off the Agent's own tenant.
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_gateway_token_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_gateway_token_hash"),
    )
    # At most one live token per (Agent, provider); revoked rows accumulate for audit.
    op.create_index(
        "uq_gateway_token_active",
        "gateway_token",
        ["agent_id", "provider"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_gateway_token_organization", "gateway_token", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_gateway_token_organization", table_name="gateway_token")
    op.drop_index("uq_gateway_token_active", table_name="gateway_token")
    op.drop_table("gateway_token")
