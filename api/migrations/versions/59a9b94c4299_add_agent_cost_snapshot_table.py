"""add_agent_cost_snapshot_table

Revision ID: 59a9b94c4299
Revises: 0dfb8ab409db
Create Date: 2026-06-13 13:25:39.639368

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "59a9b94c4299"
down_revision: Union[str, None] = "0dfb8ab409db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_cost_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("snapshotted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_cost_snapshot_agent_id", "agent_cost_snapshot", ["agent_id"], unique=False)
    op.create_index("ix_agent_cost_snapshot_organization_id", "agent_cost_snapshot", ["organization_id"], unique=False)
    op.create_index("ix_agent_cost_snapshot_snapshotted_at", "agent_cost_snapshot", ["snapshotted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_cost_snapshot_snapshotted_at", table_name="agent_cost_snapshot")
    op.drop_index("ix_agent_cost_snapshot_organization_id", table_name="agent_cost_snapshot")
    op.drop_index("ix_agent_cost_snapshot_agent_id", table_name="agent_cost_snapshot")
    op.drop_table("agent_cost_snapshot")
