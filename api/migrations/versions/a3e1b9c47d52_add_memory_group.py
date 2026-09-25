"""add memory_group and agent group membership

Revision ID: a3e1b9c47d52
Revises: 65f92c323854
Branch Labels: None
Depends On: None

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3e1b9c47d52"
down_revision: str | None = "65f92c323854"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_group",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_memory_group_org_name"),
    )
    op.create_index("ix_memory_group_organization_id", "memory_group", ["organization_id"])

    # Group membership is the opt-in: a nullable FK to the group (SET NULL so
    # deleting a group just drops membership).
    op.add_column("agent", sa.Column("memory_group_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_agent_memory_group_id",
        "agent",
        "memory_group",
        ["memory_group_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_memory_group_id", "agent", type_="foreignkey")
    op.drop_column("agent", "memory_group_id")
    op.drop_index("ix_memory_group_organization_id", table_name="memory_group")
    op.drop_table("memory_group")
