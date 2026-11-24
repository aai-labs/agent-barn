"""mcp server credentials

Revision ID: c6d45e7e2df9
Revises: f52dc88eb90b
Create Date: 2026-11-11 09:00:00.000000

Credentials for Organization MCP Servers held apart from the server row: the Organization's
OAuth sign-in for an OAuth server, and each Agent's own credential for a server, a token or
an OAuth sign-in.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d45e7e2df9"
down_revision: str | Sequence[str] | None = "f52dc88eb90b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_credential",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("credentials_encrypted", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("kind IN ('static', 'oauth')", name="ck_mcp_server_credential_kind"),
        sa.CheckConstraint(
            "status IN ('active', 'needs_sign_in', 'needs_tool_filter')", name="ck_mcp_server_credential_status"
        ),
        sa.CheckConstraint("agent_id IS NOT NULL OR kind = 'oauth'", name="ck_mcp_server_credential_org_oauth"),
        sa.ForeignKeyConstraint(
            ["mcp_server_id", "organization_id"],
            ["organization_mcp_server.id", "organization_mcp_server.organization_id"],
            name="fk_mcp_server_credential_server_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_mcp_server_credential_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_mcp_server_credential_organization",
        "mcp_server_credential",
        ["mcp_server_id"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NULL"),
    )
    op.create_index(
        "uq_mcp_server_credential_agent",
        "mcp_server_credential",
        ["mcp_server_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )
    op.create_index("ix_mcp_server_credential_agent", "mcp_server_credential", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_server_credential_agent", table_name="mcp_server_credential")
    op.drop_index("uq_mcp_server_credential_agent", table_name="mcp_server_credential")
    op.drop_index("uq_mcp_server_credential_organization", table_name="mcp_server_credential")
    op.drop_table("mcp_server_credential")
