"""Separate Organization Memory read and write grants.

Revision ID: b84e19a7302f
Revises: a63e8c941d20
"""

import sqlalchemy as sa
from alembic import op

revision = "b84e19a7302f"
down_revision = "a63e8c941d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_memory_grant", sa.Column("access", sa.String(), nullable=False, server_default="read"))
    op.drop_index("uq_agent_memory_grant_organization_memory", table_name="agent_memory_grant")
    op.create_index(
        "uq_agent_memory_grant_organization_memory",
        "agent_memory_grant",
        ["agent_id", "access"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NULL"),
    )
    op.create_check_constraint(
        "ck_agent_memory_grant_access",
        "agent_memory_grant",
        "access IN ('read', 'write') AND (source_agent_id IS NULL OR access = 'read')",
    )
    # Old Organization grants already permitted both operations. Preserve that
    # authority as two explicit rows; new API grants default to read only.
    op.execute("""INSERT INTO agent_memory_grant
        (id, created_at, updated_at, organization_id, agent_id, source_agent_id, created_by_user_id, access)
        SELECT gen_random_uuid(), created_at, updated_at, organization_id, agent_id, NULL, created_by_user_id, 'write'
        FROM agent_memory_grant WHERE source_agent_id IS NULL AND access = 'read'""")


def downgrade() -> None:
    # The old schema cannot express write-only access or independent revocation.
    op.execute("DELETE FROM agent_memory_grant WHERE access = 'write'")
    op.drop_constraint("ck_agent_memory_grant_access", "agent_memory_grant", type_="check")
    op.drop_index("uq_agent_memory_grant_organization_memory", table_name="agent_memory_grant")
    op.create_index(
        "uq_agent_memory_grant_organization_memory",
        "agent_memory_grant",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NULL"),
    )
    op.drop_column("agent_memory_grant", "access")
