"""add agent_type to agent

Revision ID: c1d2e3f4a5b6
Revises: 23b02ff828ac
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "23b02ff828ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column(
            "agent_type",
            sa.String(length=20),
            nullable=False,
            server_default="openclaw",
        ),
    )
    op.create_check_constraint(
        "ck_agent_agent_type",
        "agent",
        "agent_type IN ('openclaw', 'hermes')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_agent_type", "agent", type_="check")
    op.drop_column("agent", "agent_type")
