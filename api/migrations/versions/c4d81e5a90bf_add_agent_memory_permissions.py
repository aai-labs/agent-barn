"""add agent memory permissions

Revision ID: c4d81e5a90bf
Revises: b3f1c07d92ae
Create Date: 2026-09-04

Memory is split from agent.read/agent.update: it holds derived conclusions about
real people, and rewriting it changes what an Agent believes rather than how it is
configured — the same reasoning that gave secrets their own key.

The runtime seeder backfills these onto existing installs, but the catalogue must
also be correct from migrations alone, which is what the schema tests assert.
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4d81e5a90bf"
down_revision = "b3f1c07d92ae"
branch_labels = None
depends_on = None

MEMORY_READ_ID = UUID("eda5f5c4-5a91-54d1-9b70-149dfd20366f")
MEMORY_MANAGE_ID = UUID("3245a9b1-89f3-5ce1-a652-02c683628391")

VIEWER_ROLE_ID = UUID("c7da77aa-bf9c-5626-8bad-5e0ca5159b5d")
EDITOR_ROLE_ID = UUID("30e5e846-5e24-548f-a068-2505f774ce35")
OWNER_ROLE_ID = UUID("8f2a47ff-7caf-5ded-9027-4a16b85620b3")

# Viewer reads memory because it already reads the conversations memory is derived
# from. Editor manages it because it already holds agent.secret.manage, so this is
# no widening of trust. Owner inherits Editor's grants.
_GRANTS: list[tuple[UUID, UUID]] = [
    (VIEWER_ROLE_ID, MEMORY_READ_ID),
    (EDITOR_ROLE_ID, MEMORY_READ_ID),
    (EDITOR_ROLE_ID, MEMORY_MANAGE_ID),
    (OWNER_ROLE_ID, MEMORY_READ_ID),
    (OWNER_ROLE_ID, MEMORY_MANAGE_ID),
]


# The catalogue and system-role grants are locked by triggers that raise on any
# write. That is deliberate — they may only change through a migration — so the
# locks are lifted for the inserts and restored immediately afterwards.
_DISABLE = """
    ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability;
    ALTER TABLE agent_access_role_permissions DISABLE TRIGGER trg_system_agent_role_grant_immutability;
"""
_ENABLE = """
    ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability;
    ALTER TABLE agent_access_role_permissions ENABLE TRIGGER trg_system_agent_role_grant_immutability;
"""


def upgrade() -> None:
    op.execute(_DISABLE)
    timestamp = datetime.now(UTC)
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("key", sa.String(length=255)),
    )
    op.bulk_insert(
        permissions_table,
        [
            {"id": MEMORY_READ_ID, "created_at": timestamp, "updated_at": timestamp, "key": "agent.memory.read"},
            {"id": MEMORY_MANAGE_ID, "created_at": timestamp, "updated_at": timestamp, "key": "agent.memory.manage"},
        ],
    )

    grants_table = sa.table(
        "agent_access_role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )
    op.bulk_insert(
        grants_table,
        [{"role_id": role_id, "permission_id": permission_id} for role_id, permission_id in _GRANTS],
    )
    op.execute(_ENABLE)


def downgrade() -> None:
    op.execute(_DISABLE)
    # Grants cascade from the permission rows, but drop them explicitly so the
    # downgrade is correct on a database where the cascade is not relied upon.
    op.execute(
        sa.text("DELETE FROM agent_access_role_permissions WHERE permission_id IN (:read_id, :manage_id)").bindparams(
            read_id=str(MEMORY_READ_ID), manage_id=str(MEMORY_MANAGE_ID)
        )
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE id IN (:read_id, :manage_id)").bindparams(
            read_id=str(MEMORY_READ_ID), manage_id=str(MEMORY_MANAGE_ID)
        )
    )
    op.execute(_ENABLE)
