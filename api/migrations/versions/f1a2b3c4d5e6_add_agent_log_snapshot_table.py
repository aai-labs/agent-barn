"""add_agent_log_snapshot_table

Revision ID: f1a2b3c4d5e6
Revises: 032ff9a474bb
Create Date: 2026-07-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "032ff9a474bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_log_snapshot",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("log_text", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_log_snapshot_agent_ended",
        "agent_log_snapshot",
        ["agent_id", sa.text("session_ended_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_log_snapshot_agent_ended", table_name="agent_log_snapshot")
    op.drop_table("agent_log_snapshot")
