"""add_agent_template_skill_table

Revision ID: c89367ccd358
Revises: 032ff9a474bb
Create Date: 2026-06-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c89367ccd358"
down_revision: Union[str, None] = "032ff9a474bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_template_skill",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"], ["agent_template.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "skill_id", name="uq_agent_template_skill"),
    )
    op.create_index(
        "ix_agent_template_skill_template", "agent_template_skill", ["template_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_template_skill_template", table_name="agent_template_skill"
    )
    op.drop_table("agent_template_skill")