"""add agent_id to agent_template

Revision ID: e9b4f23c5a71
Revises: d8a3f12b4c59
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9b4f23c5a71"
down_revision: Union[str, None] = "d8a3f12b4c59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_template", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE agent_template SET agent_id = agent.id
        FROM agent WHERE agent.template_id = agent_template.id
        """
    )
    op.create_foreign_key(
        "fk_agent_template_agent_id",
        "agent_template",
        "agent",
        ["agent_id"],
        ["id"],
    )
    op.create_index(
        "ix_agent_template_agent_version",
        "agent_template",
        ["agent_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_template_agent_version", table_name="agent_template")
    op.drop_constraint(
        "fk_agent_template_agent_id", "agent_template", type_="foreignkey"
    )
    op.drop_column("agent_template", "agent_id")
