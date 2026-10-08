"""add Agent Memory opt-in, Memory Grants and their Permissions

Adds `agent.memory_enabled`, the `agent_memory_grant` table, and two Permissions:
`agent.memory.manage` (granted to the locked Agent Owner role) and
`memory.access.manage` (an Organization Permission, so it has no database grant).

The Permission catalogue and system role grants are immutable by trigger. This is a
deliberate catalogue change, so the triggers are disabled only around these inserts.

Revision ID: c3e8a1f4d927
Revises: 45bcefcb0749
Create Date: 2026-10-03

"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e8a1f4d927"
down_revision: str | Sequence[str] | None = "45bcefcb0749"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_MEMORY_MANAGE_ID = UUID("a0a4981e-d2da-534e-9258-e7fb8e76e08e")
MEMORY_ACCESS_MANAGE_ID = UUID("77c885cb-06d0-5fd3-a990-60c129c273f6")
AGENT_OWNER_ROLE_ID = UUID("8f2a47ff-7caf-5ded-9027-4a16b85620b3")


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "agent_memory_grant",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_memory_grant_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_memory_grant_source_agent_organization",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_agent_id IS NULL OR source_agent_id <> agent_id",
            name="ck_agent_memory_grant_not_self",
        ),
    )
    op.create_index(
        "uq_agent_memory_grant_organization_memory",
        "agent_memory_grant",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NULL"),
    )
    op.create_index(
        "uq_agent_memory_grant_agent_source",
        "agent_memory_grant",
        ["agent_id", "source_agent_id"],
        unique=True,
        postgresql_where=sa.text("source_agent_id IS NOT NULL"),
    )
    op.create_index("ix_agent_memory_grant_organization", "agent_memory_grant", ["organization_id"])
    op.create_index("ix_agent_memory_grant_source_agent", "agent_memory_grant", ["source_agent_id"])

    timestamp = datetime.now(UTC)
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.execute("ALTER TABLE agent_access_role_permissions DISABLE TRIGGER trg_system_agent_role_grant_immutability")
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
            sa.column("key", sa.String(length=255)),
        ),
        [
            {
                "id": AGENT_MEMORY_MANAGE_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
                "key": "agent.memory.manage",
            },
            {
                "id": MEMORY_ACCESS_MANAGE_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
                "key": "memory.access.manage",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "agent_access_role_permissions",
            sa.column("role_id", postgresql.UUID(as_uuid=True)),
            sa.column("permission_id", postgresql.UUID(as_uuid=True)),
        ),
        [{"role_id": AGENT_OWNER_ROLE_ID, "permission_id": AGENT_MEMORY_MANAGE_ID}],
    )
    op.execute("ALTER TABLE agent_access_role_permissions ENABLE TRIGGER trg_system_agent_role_grant_immutability")
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def downgrade() -> None:
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.execute("ALTER TABLE agent_access_role_permissions DISABLE TRIGGER trg_system_agent_role_grant_immutability")
    # Custom Agent Access Roles may also hold agent.memory.manage; drop every grant of it.
    op.execute(
        sa.text("DELETE FROM agent_access_role_permissions WHERE permission_id = :permission_id").bindparams(
            permission_id=AGENT_MEMORY_MANAGE_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE id IN (:agent_memory, :memory_access)").bindparams(
            agent_memory=AGENT_MEMORY_MANAGE_ID, memory_access=MEMORY_ACCESS_MANAGE_ID
        )
    )
    op.execute("ALTER TABLE agent_access_role_permissions ENABLE TRIGGER trg_system_agent_role_grant_immutability")
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")

    op.drop_index("ix_agent_memory_grant_source_agent", table_name="agent_memory_grant")
    op.drop_index("ix_agent_memory_grant_organization", table_name="agent_memory_grant")
    op.drop_index("uq_agent_memory_grant_agent_source", table_name="agent_memory_grant")
    op.drop_index("uq_agent_memory_grant_organization_memory", table_name="agent_memory_grant")
    op.drop_table("agent_memory_grant")
    op.drop_column("agent", "memory_enabled")
