"""add agent_skill table

Revision ID: a7d4e2f10b93
Revises: f3a91c7b2e58
Create Date: 2026-06-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d4e2f10b93"
down_revision: Union[str, None] = "f3a91c7b2e58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_skill",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("skill_name", sa.String(length=255), nullable=False),
        sa.Column("skill_file_path", sa.String(length=1024), nullable=False),
        sa.Column("skill_content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "skill_file_path", name="uq_agent_skill_agent_file_path"
        ),
        sa.CheckConstraint(
            "source IN ('aai_cli', 'custom')",
            name="ck_agent_skill_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_skill")
