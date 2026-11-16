"""agent mcp servers and restricted servers

Revision ID: d3a8b61f4c20
Revises: c6d45e7e2df9
Create Date: 2026-11-11 15:00:00.000000

Agent MCP Servers: an MCP server row may belong to one Agent (`agent_id`, scope `agent`)
instead of the whole Organization, with identifiers unique per Agent. Organization servers
gain `restricted`, which keeps attaching them and Agent credentials for them to Owners and
Admins.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a8b61f4c20"
down_revision: str | Sequence[str] | None = "c6d45e7e2df9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "organization_mcp_server"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("restricted", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column(_TABLE, sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_organization_mcp_server_agent_organization",
        _TABLE,
        "agent",
        ["agent_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_organization_mcp_server_scope", _TABLE, type_="check")
    op.create_check_constraint(
        "ck_organization_mcp_server_scope", _TABLE, "scope IN ('all_agents', 'selected_agents', 'agent')"
    )
    op.create_check_constraint(
        "ck_organization_mcp_server_agent_scope", _TABLE, "(scope = 'agent') = (agent_id IS NOT NULL)"
    )
    op.create_check_constraint(
        "ck_organization_mcp_server_restricted", _TABLE, "NOT (restricted AND agent_id IS NOT NULL)"
    )
    op.drop_constraint("uq_organization_mcp_server_identifier", _TABLE, type_="unique")
    op.create_index(
        "uq_organization_mcp_server_identifier",
        _TABLE,
        ["organization_id", "identifier"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NULL"),
    )
    op.create_index(
        "uq_organization_mcp_server_agent_identifier",
        _TABLE,
        ["agent_id", "identifier"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )
    op.create_index("ix_organization_mcp_server_agent", _TABLE, ["agent_id"])


def downgrade() -> None:
    # Agent servers have no place in the earlier schema.
    op.execute(f"DELETE FROM {_TABLE} WHERE agent_id IS NOT NULL")
    op.drop_index("ix_organization_mcp_server_agent", table_name=_TABLE)
    op.drop_index("uq_organization_mcp_server_agent_identifier", table_name=_TABLE)
    op.drop_index("uq_organization_mcp_server_identifier", table_name=_TABLE)
    op.create_unique_constraint("uq_organization_mcp_server_identifier", _TABLE, ["organization_id", "identifier"])
    op.drop_constraint("ck_organization_mcp_server_restricted", _TABLE, type_="check")
    op.drop_constraint("ck_organization_mcp_server_agent_scope", _TABLE, type_="check")
    op.drop_constraint("ck_organization_mcp_server_scope", _TABLE, type_="check")
    op.create_check_constraint("ck_organization_mcp_server_scope", _TABLE, "scope IN ('all_agents', 'selected_agents')")
    op.drop_constraint("fk_organization_mcp_server_agent_organization", _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "agent_id")
    op.drop_column(_TABLE, "restricted")
