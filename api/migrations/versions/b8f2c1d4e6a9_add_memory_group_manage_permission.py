"""add memory_group.manage permission

Revision ID: b8f2c1d4e6a9
Revises: a3e1b9c47d52
Create Date: 2026-09-21

An org-scoped management permission (create/rename/delete memory groups, assign
Agents). Org-role grants live in code (catalog.py), so only the permission row is
seeded here — no agent_access_role_permissions grant. The runtime seeder backfills
existing installs, but the catalogue must also be correct from migrations alone,
which the schema tests assert.
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8f2c1d4e6a9"
down_revision = "a3e1b9c47d52"
branch_labels = None
depends_on = None

MEMORY_GROUP_MANAGE_ID = UUID("cefd77e7-0e67-500e-8fe4-37879667c6e6")

# The permission catalogue is trigger-locked; it may only change through a
# migration, so the lock is lifted for the insert and restored immediately after.
_DISABLE = "ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability;"
_ENABLE = "ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability;"


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
            {
                "id": MEMORY_GROUP_MANAGE_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
                "key": "memory_group.manage",
            },
        ],
    )
    op.execute(_ENABLE)


def downgrade() -> None:
    op.execute(_DISABLE)
    op.execute(sa.text("DELETE FROM permissions WHERE id = :pid").bindparams(pid=str(MEMORY_GROUP_MANAGE_ID)))
    op.execute(_ENABLE)
