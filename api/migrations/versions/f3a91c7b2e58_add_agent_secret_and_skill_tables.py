"""add agent_secret and agent_skill tables

Revision ID: f3a91c7b2e58
Revises: 23b02ff828ac
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a91c7b2e58"
down_revision: Union[str, None] = "23b02ff828ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_secret",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("secret_name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "provider", name="uq_agent_secret_agent_provider"
        ),
        sa.CheckConstraint(
            "provider IN ('github', 'jira', 'confluence', 'bitbucket', "
            "'gmail', 'google_calendar', 'zoho_mail', 'zoho_calendar')",
            name="ck_agent_secret_provider",
        ),
    )
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
    op.drop_table("agent_secret")
