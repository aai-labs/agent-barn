"""drop tool_call_sync_state table

Revision ID: ab2b4bb88c6f
Revises: e9cad4733449
Create Date: 2026-06-29 12:12:09.760689

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ab2b4bb88c6f"
down_revision: Union[str, None] = "e9cad4733449"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("tool_call_sync_state")


def downgrade() -> None:
    op.create_table(
        "tool_call_sync_state",
        sa.Column("id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("agent_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("session_file_path", sa.String(), nullable=False),
        sa.Column("last_byte_offset", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "session_file_path", name="uq_tcss_agent_file"),
    )
