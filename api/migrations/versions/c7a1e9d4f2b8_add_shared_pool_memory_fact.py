"""add shared pool memory fact

Revision ID: c7a1e9d4f2b8
Revises: b8f2c1d4e6a9
Create Date: 2026-09-21

Provenance for memories shared from one memory pool (group) into another. The
group-level counterpart of shared_memory_fact: Honcho conclusions carry no
metadata, so a fact copied into a pool is indistinguishable from one the pool
derived itself. These rows are that distinction, joined back on read to badge the
item "Shared from <group>". Lives alongside the agent-level table so the memory
read path can join it without a cross-domain cycle.
"""

import sqlalchemy as sa
from alembic import op

revision = "c7a1e9d4f2b8"
down_revision = "b8f2c1d4e6a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shared_pool_memory_fact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conclusion_id", sa.String(length=255), nullable=False),
        sa.Column("target_group_id", sa.Uuid(), nullable=False),
        sa.Column("source_group_id", sa.Uuid(), nullable=True),
        sa.Column("shared_by_user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # A second row for one conclusion would mean two origins claimed for it.
        sa.UniqueConstraint("conclusion_id", name="uq_shared_pool_memory_fact_conclusion_id"),
        # CASCADE: deleting a group erases its pool, so a row describing memory in
        # that pool has nothing left to explain.
        sa.ForeignKeyConstraint(["target_group_id"], ["memory_group.id"], ondelete="CASCADE"),
        # SET NULL, not CASCADE: deleting the source group must not erase the badge
        # on a memory the destination pool still holds.
        sa.ForeignKeyConstraint(["source_group_id"], ["memory_group.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_shared_pool_memory_fact_target_group", "shared_pool_memory_fact", ["target_group_id"])


def downgrade() -> None:
    op.drop_index("ix_shared_pool_memory_fact_target_group", table_name="shared_pool_memory_fact")
    op.drop_table("shared_pool_memory_fact")
