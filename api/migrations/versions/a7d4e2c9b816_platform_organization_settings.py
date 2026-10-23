"""platform organization settings

Revision ID: a7d4e2c9b816
Revises: f1c7e3a92b05
Create Date: 2026-10-14 12:00:00.000000

Platform-wide Organization settings (AF-381): a singleton holding the default Agent limit
for Organizations that aren't trials. The deployment's ORGANIZATION_DEFAULT_AGENT_LIMIT
applies until the first save.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4e2c9b816"
down_revision: str | Sequence[str] | None = "f1c7e3a92b05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_organization_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_agent_limit", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_organization_settings_singleton"),
        sa.CheckConstraint(
            "default_agent_limit >= 1", name="ck_platform_organization_settings_default_agent_limit_positive"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_organization_settings")
