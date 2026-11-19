"""Workflows are on for every installation: drop the Platform workflow authoring setting.

Revision ID: 463f987cd60d
Revises: 0a07b0b57b62
"""

import sqlalchemy as sa
from alembic import op

revision: str = "463f987cd60d"
down_revision: str | None = "0a07b0b57b62"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_table("platform_workflow_settings")


def downgrade() -> None:
    op.create_table(
        "platform_workflow_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("authoring_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_workflow_settings_singleton"),
    )
    # The earlier API reads a missing row as off; keep workflows on after a rollback.
    op.execute("INSERT INTO platform_workflow_settings (id, authoring_enabled, updated_at) VALUES (1, true, now())")
