"""add the origin of an Agent Task

`agent` for a Task the Agent recorded itself, `automatic` for one its runtime's Task
plugin recorded because the Agent did work without recording it. Existing Tasks were
all recorded by their Agents.

Revision ID: e5a1c9f3d208
Revises: d2f8a6c41e07
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5a1c9f3d208"
down_revision: str | Sequence[str] | None = "d2f8a6c41e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_task_origin_enum = postgresql.ENUM("agent", "automatic", name="agenttaskorigin", create_type=False)


def upgrade() -> None:
    agent_task_origin_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agent_task",
        sa.Column("origin", agent_task_origin_enum, nullable=False, server_default="agent"),
    )


def downgrade() -> None:
    op.drop_column("agent_task", "origin")
    agent_task_origin_enum.drop(op.get_bind(), checkfirst=True)
