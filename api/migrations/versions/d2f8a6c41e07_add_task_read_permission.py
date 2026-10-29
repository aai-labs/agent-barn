"""add the task.read Permission

Grants `task.read` to every locked Agent Access Role, so anyone who can view an Agent
can read its Tasks, Task Notes and Task Files.

The Permission catalogue and system role grants are immutable by trigger. This is a
deliberate catalogue change, so the triggers are disabled only around these inserts.

Revision ID: d2f8a6c41e07
Revises: b7d4e1a9c362
Create Date: 2026-10-21

"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2f8a6c41e07"
down_revision: str | Sequence[str] | None = "b7d4e1a9c362"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_READ_ID = UUID("cb4bbe39-bbc4-5569-b1f4-8aeefa91b419")
AGENT_OWNER_ROLE_ID = UUID("8f2a47ff-7caf-5ded-9027-4a16b85620b3")
AGENT_EDITOR_ROLE_ID = UUID("30e5e846-5e24-548f-a068-2505f774ce35")
AGENT_VIEWER_ROLE_ID = UUID("c7da77aa-bf9c-5626-8bad-5e0ca5159b5d")


def upgrade() -> None:
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
        [{"id": TASK_READ_ID, "created_at": timestamp, "updated_at": timestamp, "key": "task.read"}],
    )
    op.bulk_insert(
        sa.table(
            "agent_access_role_permissions",
            sa.column("role_id", postgresql.UUID(as_uuid=True)),
            sa.column("permission_id", postgresql.UUID(as_uuid=True)),
        ),
        [
            {"role_id": role_id, "permission_id": TASK_READ_ID}
            for role_id in (AGENT_VIEWER_ROLE_ID, AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID)
        ],
    )
    op.execute("ALTER TABLE agent_access_role_permissions ENABLE TRIGGER trg_system_agent_role_grant_immutability")
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def downgrade() -> None:
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.execute("ALTER TABLE agent_access_role_permissions DISABLE TRIGGER trg_system_agent_role_grant_immutability")
    # Custom Agent Access Roles may also hold task.read; drop every grant of it.
    op.execute(
        sa.text("DELETE FROM agent_access_role_permissions WHERE permission_id = :permission_id").bindparams(
            permission_id=TASK_READ_ID
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE id = :id").bindparams(id=TASK_READ_ID))
    op.execute("ALTER TABLE agent_access_role_permissions ENABLE TRIGGER trg_system_agent_role_grant_immutability")
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")
