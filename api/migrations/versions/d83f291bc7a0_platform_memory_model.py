"""Persist the platform-wide memory processing model.
Revision ID: d83f291bc7a0
Revises: c95f20b8413a
"""

import sqlalchemy as sa
from alembic import op

revision = "d83f291bc7a0"
down_revision = "c95f20b8413a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_memory_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_memory_settings_singleton"),
    )


def downgrade():
    op.drop_table("platform_memory_settings")
