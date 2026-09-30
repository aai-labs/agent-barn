"""Add organization_agent_settings

Revision ID: b3d17c9a5e42
Revises: d5e2a9f4c781
Create Date: 2026-08-19 10:00:00.000000

Organization-scoped Agent defaults, starting with the runtime model. No backfill:
a missing row and a NULL column both mean "follow the platform default", so every
existing Organization keeps tracking AGENT_DEFAULT_MODEL until an owner picks
something else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d17c9a5e42"
down_revision: str | None = "d5e2a9f4c781"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_agent_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("default_model", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_organization_agent_settings_organization_id"),
    )


def downgrade() -> None:
    op.drop_table("organization_agent_settings")
