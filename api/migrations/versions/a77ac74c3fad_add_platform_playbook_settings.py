"""Persist the platform-wide Playbook Extraction model.

Revision ID: a77ac74c3fad
Revises: 5ae205b73312
"""

import sqlalchemy as sa
from alembic import op

revision = "a77ac74c3fad"
down_revision = "5ae205b73312"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_playbook_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_playbook_settings_singleton"),
    )


def downgrade():
    op.drop_table("platform_playbook_settings")
