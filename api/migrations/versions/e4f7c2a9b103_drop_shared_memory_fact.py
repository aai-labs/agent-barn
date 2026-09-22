"""drop shared memory fact

Revision ID: e4f7c2a9b103
Revises: c7a1e9d4f2b8
Create Date: 2026-09-22

The per-Agent explicit-sharing surface (share-fact / carry-over) is removed: the
pool model shares memory within a group automatically, and cross-group sharing is
its own path tracked in shared_pool_memory_fact. The agent-level provenance table
this backed is no longer written or read, so it is dropped.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f7c2a9b103"
down_revision = "c7a1e9d4f2b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_shared_memory_fact_target_agent", table_name="shared_memory_fact")
    op.drop_table("shared_memory_fact")


def downgrade() -> None:
    op.create_table(
        "shared_memory_fact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conclusion_id", sa.String(length=255), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=False),
        sa.Column("source_agent_id", sa.Uuid(), nullable=True),
        sa.Column("shared_by_user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conclusion_id", name="uq_shared_memory_fact_conclusion_id"),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_agent_id"], ["agent.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_shared_memory_fact_target_agent", "shared_memory_fact", ["target_agent_id"])
