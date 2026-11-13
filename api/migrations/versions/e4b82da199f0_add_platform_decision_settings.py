"""Persist the platform-wide decision model.

Revision ID: e4b82da199f0
Revises: a9d2e7c4b1f8
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b82da199f0"
down_revision = "a9d2e7c4b1f8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_decision_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_decision_settings_singleton"),
    )


def downgrade():
    op.drop_table("platform_decision_settings")
