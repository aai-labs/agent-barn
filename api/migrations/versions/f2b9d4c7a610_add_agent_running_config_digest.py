"""Record the runtime configuration digest an Agent's pod started on.

Revision ID: f2b9d4c7a610
Revises: 43ac1fbc7ff1
"""

import sqlalchemy as sa
from alembic import op

revision: str = "f2b9d4c7a610"
down_revision: str | None = "43ac1fbc7ff1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("running_config_digest", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("agent", "running_config_digest")
