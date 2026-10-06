"""Give each Agent its own runtime image pin.

Revision ID: 2482afb7a62b
Revises: d7a2c4f81b36
"""

import sqlalchemy as sa
from alembic import op

revision: str = "2482afb7a62b"
down_revision: str | None = "d7a2c4f81b36"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("pinned_runtime_image", sa.String(255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("agent", "pinned_runtime_image")
