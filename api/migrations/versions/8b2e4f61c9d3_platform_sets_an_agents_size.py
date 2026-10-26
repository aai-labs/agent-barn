"""A Platform Administrator sets one Agent's size

Revision ID: 8b2e4f61c9d3
Revises: 3046153d9447
Create Date: 2026-10-22

Agent Sizes, PR 3. `agent.agent_size_set_by_platform` marks an Agent whose size a Platform
Administrator set. While it is true the Organization cannot change the size; clearing the
override puts the Agent back on the default and turns it off.

Every existing Agent gets false, so nothing it chose changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b2e4f61c9d3"
down_revision: str | Sequence[str] | None = "3046153d9447"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("agent_size_set_by_platform", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent", "agent_size_set_by_platform")
