"""Persist the platform-wide workflow authoring setting.

Revision ID: a38802d7f002
Revises: a38801c6e001
"""

import sqlalchemy as sa
from alembic import op

revision = "a38802d7f002"
down_revision = "a38801c6e001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_workflow_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("authoring_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_workflow_settings_singleton"),
    )


def downgrade() -> None:
    op.drop_table("platform_workflow_settings")
