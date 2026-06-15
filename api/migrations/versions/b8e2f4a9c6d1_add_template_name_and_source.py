"""add template_name and template_source to agent_template

Revision ID: b8e2f4a9c6d1
Revises: a4d7c2e8f1b3
Create Date: 2026-06-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2f4a9c6d1"
down_revision: Union[str, None] = "a4d7c2e8f1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_template",
        sa.Column("template_name", sa.String(length=255), nullable=True),
    )
    # Legacy per-agent lineages have no display name; the slug is the best we have.
    op.execute("UPDATE agent_template SET template_name = template_slug")
    op.alter_column("agent_template", "template_name", nullable=False)

    op.add_column(
        "agent_template",
        sa.Column(
            "template_source",
            sa.String(length=20),
            nullable=False,
            server_default="custom",
        ),
    )
    op.create_check_constraint(
        "ck_agent_template_template_source",
        "agent_template",
        "template_source IN ('pre-defined', 'custom')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_template_template_source", "agent_template", type_="check"
    )
    op.drop_column("agent_template", "template_source")
    op.drop_column("agent_template", "template_name")
