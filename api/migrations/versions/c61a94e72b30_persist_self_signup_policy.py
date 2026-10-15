"""Persist self-signup policy with the platform trial settings.

Revision ID: c61a94e72b30
Revises: b3d8e1f4a6c2
"""

import sqlalchemy as sa
from alembic import op

revision = "c61a94e72b30"
down_revision = "b3d8e1f4a6c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_trial_settings",
        sa.Column("self_signup_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "ck_platform_trial_settings_signup_credit",
        "platform_trial_settings",
        "NOT self_signup_enabled OR credit_usd > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_platform_trial_settings_signup_credit", "platform_trial_settings", type_="check")
    op.drop_column("platform_trial_settings", "self_signup_enabled")
