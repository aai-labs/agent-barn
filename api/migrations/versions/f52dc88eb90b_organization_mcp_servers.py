"""organization mcp servers

Revision ID: f52dc88eb90b
Revises: 3f9f88255e3b
Create Date: 2026-11-10 18:00:00.000000

Organization MCP Servers: the remote MCP servers an Organization registers for its
Agents, each Agent's opt-in to a Selected Agents server, the gateway token each running
Agent presents for them, and the `mcp_server.manage` Permission, which Owners and Admins
hold.

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "f52dc88eb90b"
down_revision: str | Sequence[str] | None = "3f9f88255e3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when it
# shipped, whatever the catalogue in code says later.
MCP_SERVER_MANAGE_ID = UUID("9649cb6a-fc1a-51b1-9160-8b13c09de27a")
MCP_SERVER_MANAGE_KEY = "mcp_server.manage"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.create_table(
        "organization_mcp_server",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("identifier", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("credentials_encrypted", sa.String(), nullable=False),
        sa.Column("tool_include", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("tool_exclude", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("scope IN ('all_agents', 'selected_agents')", name="ck_organization_mcp_server_scope"),
        sa.CheckConstraint(
            "tool_include IS NULL OR tool_exclude IS NULL", name="ck_organization_mcp_server_one_tool_filter"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "identifier", name="uq_organization_mcp_server_identifier"),
        sa.UniqueConstraint("id", "organization_id", name="uq_organization_mcp_server_id_organization"),
    )
    op.create_index(op.f("ix_organization_mcp_server_organization_id"), "organization_mcp_server", ["organization_id"])
    op.create_table(
        "agent_mcp_server_attachment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_mcp_server_attachment_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id", "organization_id"],
            ["organization_mcp_server.id", "organization_mcp_server.organization_id"],
            name="fk_agent_mcp_server_attachment_server_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "mcp_server_id", name="uq_agent_mcp_server_attachment"),
    )
    op.create_index("ix_agent_mcp_server_attachment_server", "agent_mcp_server_attachment", ["mcp_server_id"])
    op.create_table(
        "agent_mcp_gateway_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_mcp_gateway_token_agent_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_mcp_gateway_token_agent"),
        sa.UniqueConstraint("token_hash", name="uq_agent_mcp_gateway_token_hash"),
    )
    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=MCP_SERVER_MANAGE_ID,
        key=MCP_SERVER_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=MCP_SERVER_MANAGE_ID)
    op.drop_table("agent_mcp_gateway_token")
    op.drop_index("ix_agent_mcp_server_attachment_server", table_name="agent_mcp_server_attachment")
    op.drop_table("agent_mcp_server_attachment")
    op.drop_index(op.f("ix_organization_mcp_server_organization_id"), table_name="organization_mcp_server")
    op.drop_table("organization_mcp_server")
