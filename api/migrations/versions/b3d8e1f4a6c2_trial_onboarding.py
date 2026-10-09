"""trial onboarding

Revision ID: b3d8e1f4a6c2
Revises: 164fb0fb6c2c
Create Date: 2026-10-07 12:00:00.000000

Google sign-in and trial onboarding (AF-368): the Google account a User signs in
with, when they signed themselves up and finished onboarding, which Organizations
are trials, the platform's trial settings, and which email addresses have had a
trial. Every existing Organization stays a non-trial.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d8e1f4a6c2"
down_revision: str | Sequence[str] | None = "164fb0fb6c2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("user", sa.Column("signed_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user", sa.Column("trial_ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_user_google_sub", "user", ["google_sub"], unique=True)
    op.add_column("organization", sa.Column("is_trial", sa.Boolean(), server_default="false", nullable=False))
    op.create_table(
        "platform_trial_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credit_usd", sa.Float(), nullable=False),
        sa.Column("agent_limit", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_active_trials", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_platform_trial_settings_singleton"),
        sa.CheckConstraint("credit_usd >= 0", name="ck_platform_trial_settings_credit_non_negative"),
        sa.CheckConstraint("agent_limit >= 1", name="ck_platform_trial_settings_agent_limit_positive"),
        sa.CheckConstraint("max_active_trials >= 1", name="ck_platform_trial_settings_max_active_trials_positive"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trial_grant",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("email_hash"),
    )


def downgrade() -> None:
    op.drop_table("trial_grant")
    op.drop_table("platform_trial_settings")
    op.drop_column("organization", "is_trial")
    op.drop_index("ix_user_google_sub", table_name="user")
    op.drop_column("user", "onboarding_completed_at")
    op.drop_column("user", "trial_ended_at")
    op.drop_column("user", "signed_up_at")
    op.drop_column("user", "google_sub")
