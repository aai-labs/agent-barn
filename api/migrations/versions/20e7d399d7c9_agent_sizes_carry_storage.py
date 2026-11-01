"""Agent Sizes carry the storage of an Agent's volume

Revision ID: 20e7d399d7c9
Revises: 8b2e4f61c9d3
Create Date: 2026-10-26

Every Agent's volume (PVC) was a fixed 1Gi. A size now says how large it is: a new volume is
created at that size, and an existing one grows to it at the Agent's next start (a volume is
never shrunk). Every existing size gets 1Gi, so every Agent keeps exactly the volume it has.

`agent.running_resources` gains `storage_bytes` at each start; a record written before this,
which lacks it, is read as the 1Gi every volume then had, so nothing is backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20e7d399d7c9"
down_revision: str | Sequence[str] | None = "8b2e4f61c9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONE_GIB = 1024**3


def upgrade() -> None:
    op.add_column(
        "agent_sizes",
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False, server_default=sa.text(str(_ONE_GIB))),
    )
    # The default only fills the existing rows; the API always names a value from here on.
    op.alter_column("agent_sizes", "storage_bytes", server_default=None)
    op.create_check_constraint("ck_agent_sizes_storage_positive", "agent_sizes", "storage_bytes > 0")


def downgrade() -> None:
    op.drop_constraint("ck_agent_sizes_storage_positive", "agent_sizes", type_="check")
    op.drop_column("agent_sizes", "storage_bytes")
