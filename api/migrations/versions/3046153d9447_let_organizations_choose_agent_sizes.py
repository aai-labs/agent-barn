"""Let Organizations choose an Agent Size

Revision ID: 3046153d9447
Revises: dd9ef852a427
Create Date: 2026-10-22

Agent Sizes, PR 2. A Platform Administrator allows an Organization a set of sizes
(`organization_agent_sizes`; no rows means it cannot choose, and the default is always
choosable without a row). An Agent records the size its Organization chose
(`agent.agent_size_id`, NULL following the platform default) and the requests and limits its
running pod was started with (`agent.running_resources`, NULL when not running).

Every existing Agent gets NULL for both, so it keeps starting on the default, which PR 1 seeded
with the values the builders always used. `agent.size.manage` is added to the Permission
catalogue; Organization Owners and Admins hold it through their role, from code.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3046153d9447"
down_revision: str | Sequence[str] | None = "dd9ef852a427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the catalogue in code says later.
AGENT_SIZE_MANAGE_ID = UUID("bdca6a6b-54cd-5741-98ef-6cdc10cfea69")
AGENT_SIZE_MANAGE_KEY = "agent.size.manage"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.create_table(
        "organization_agent_sizes",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_size_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_size_id"], ["agent_sizes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "agent_size_id"),
    )
    # The primary key serves lookups by Organization; this serves "who allows this size".
    op.create_index("ix_organization_agent_sizes_agent_size_id", "organization_agent_sizes", ["agent_size_id"])

    op.add_column("agent", sa.Column("agent_size_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "agent_agent_size_id_fkey", "agent", "agent_sizes", ["agent_size_id"], ["id"], ondelete="RESTRICT"
    )
    # Deleting a size asks whether any Agent references it.
    op.create_index("ix_agent_agent_size_id", "agent", ["agent_size_id"])
    op.add_column("agent", sa.Column("running_resources", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=AGENT_SIZE_MANAGE_ID,
        key=AGENT_SIZE_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=AGENT_SIZE_MANAGE_ID)

    op.drop_column("agent", "running_resources")
    op.drop_index("ix_agent_agent_size_id", table_name="agent")
    op.drop_constraint("agent_agent_size_id_fkey", "agent", type_="foreignkey")
    op.drop_column("agent", "agent_size_id")

    op.drop_index("ix_organization_agent_sizes_agent_size_id", table_name="organization_agent_sizes")
    op.drop_table("organization_agent_sizes")
