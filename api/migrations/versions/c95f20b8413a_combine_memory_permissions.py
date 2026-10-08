"""Use Read only or Read and write Organization Memory permissions.

Revision ID: c95f20b8413a
Revises: b84e19a7302f
"""

import sqlalchemy as sa
from alembic import op

revision = "c95f20b8413a"
down_revision = "b84e19a7302f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_agent_memory_grant_access", "agent_memory_grant", type_="check")
    op.drop_index("uq_agent_memory_grant_organization_memory", table_name="agent_memory_grant")
    # Keep the original writer record and provenance when both grants exist.
    op.execute("""DELETE FROM agent_memory_grant AS reader
        USING agent_memory_grant AS writer
        WHERE reader.agent_id = writer.agent_id AND reader.source_agent_id IS NULL
        AND writer.source_agent_id IS NULL AND reader.access = 'read' AND writer.access = 'write'""")
    op.execute("UPDATE agent_memory_grant SET access = 'read_write' WHERE access = 'write'")
    op.create_check_constraint(
        "ck_agent_memory_grant_access",
        "agent_memory_grant",
        "access IN ('read', 'read_write') AND (source_agent_id IS NULL OR access = 'read')",
    )
    op.create_index(
        "uq_agent_memory_grant_organization_memory",
        "agent_memory_grant",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_memory_grant_access", "agent_memory_grant", type_="check")
    op.drop_index("uq_agent_memory_grant_organization_memory", table_name="agent_memory_grant")
    op.execute("UPDATE agent_memory_grant SET access = 'write' WHERE access = 'read_write'")
    op.execute("""INSERT INTO agent_memory_grant
        (id, created_at, updated_at, organization_id, agent_id, source_agent_id, created_by_user_id, access)
        SELECT gen_random_uuid(), created_at, updated_at, organization_id, agent_id, NULL, created_by_user_id, 'read'
        FROM agent_memory_grant WHERE source_agent_id IS NULL AND access = 'write'""")
    op.create_check_constraint(
        "ck_agent_memory_grant_access",
        "agent_memory_grant",
        "access IN ('read', 'write') AND (source_agent_id IS NULL OR access = 'read')",
    )
    op.create_index(
        "uq_agent_memory_grant_organization_memory",
        "agent_memory_grant",
        ["agent_id", "access"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NULL"),
    )
