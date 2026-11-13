"""index Agent Tasks by last change

Task lists put the most recently changed Task first, for one Agent or the whole
Organization, so both orders get an index.

Revision ID: f1c6a8d3e5b7
Revises: d4b8e2f6a9c3
Create Date: 2026-11-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c6a8d3e5b7"
down_revision: str | Sequence[str] | None = "d4b8e2f6a9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_task_organization_agent_updated", "agent_task", ["organization_id", "agent_id", "updated_at"]
    )
    op.create_index("ix_agent_task_organization_updated", "agent_task", ["organization_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_task_organization_updated", table_name="agent_task")
    op.drop_index("ix_agent_task_organization_agent_updated", table_name="agent_task")
