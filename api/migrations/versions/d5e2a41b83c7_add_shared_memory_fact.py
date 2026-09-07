"""add shared memory fact

Revision ID: d5e2a41b83c7
Revises: c4d81e5a90bf
Create Date: 2026-09-04

Provenance for memories one Agent was handed by another. Honcho's conclusions
carry no metadata, and a shared fact is written onto the destination's own
self-model — exactly where its self-derived conclusions live — so nothing in
Honcho distinguishes the two. These rows are that distinction, joined back on
read so the memory view can stop calling a shared fact "about itself".
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e2a41b83c7"
down_revision = "c4d81e5a90bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        # A second row for one conclusion would mean two origins claimed for the
        # same memory.
        sa.UniqueConstraint("conclusion_id", name="uq_shared_memory_fact_conclusion_id"),
        # CASCADE: if the destination is hard-deleted its memory goes with it, so a
        # row describing that memory has nothing left to explain.
        sa.ForeignKeyConstraint(["target_agent_id"], ["agent.id"], ondelete="CASCADE"),
        # SET NULL, not CASCADE: hard-deleting the source must not erase the badge on
        # a memory the destination still holds. "Shared from an Agent that no longer
        # exists" beats silently reverting to "figured this out itself".
        sa.ForeignKeyConstraint(["source_agent_id"], ["agent.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["user.id"]),
    )
    # Every read is "the shared facts for this Agent", never a scan.
    op.create_index("ix_shared_memory_fact_target_agent", "shared_memory_fact", ["target_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_shared_memory_fact_target_agent", table_name="shared_memory_fact")
    op.drop_table("shared_memory_fact")
