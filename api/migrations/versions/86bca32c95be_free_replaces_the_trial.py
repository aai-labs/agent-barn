"""Free replaces the trial

Revision ID: 86bca32c95be
Revises: 55e07653f502
Create Date: 2026-11-08

A trial is an Organization on the Free Tier. The trial's credit and Agent
limit move from `platform_trial_settings` onto the Free row, and Free is offered exactly
where self-signup already is. Every existing trial moves onto Free. A trial that runs
more than Free covers gets 14 days (`organization.tier_holds_due_at`) for its Owner to
choose what to keep before the oldest Agents are kept automatically. Organizations that
were never trials stay on no Tier.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86bca32c95be"
down_revision: str | Sequence[str] | None = "55e07653f502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FREE_TIER_ID = "00000000-0000-7000-8000-0000000071e0"
CHOOSING_DAYS = 14


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE tier SET
            one_time_credit_usd = settings.credit_usd,
            agent_limit = settings.agent_limit,
            enabled = settings.self_signup_enabled,
            updated_at = now()
        FROM platform_trial_settings AS settings
        WHERE settings.id = 1 AND tier.activation = 'free' AND tier.id = '{FREE_TIER_ID}'
        """
    )
    op.add_column("organization", sa.Column("tier_holds_due_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        f"""
        UPDATE organization SET
            tier_id = '{FREE_TIER_ID}',
            tier_holds_due_at = now() + interval '{CHOOSING_DAYS} days'
        WHERE is_trial AND tier_id IS NULL
        """
    )
    op.drop_constraint("ck_platform_trial_settings_signup_credit", "platform_trial_settings", type_="check")
    op.drop_constraint("ck_platform_trial_settings_credit_non_negative", "platform_trial_settings", type_="check")
    op.drop_constraint("ck_platform_trial_settings_agent_limit_positive", "platform_trial_settings", type_="check")
    op.drop_column("platform_trial_settings", "credit_usd")
    op.drop_column("platform_trial_settings", "agent_limit")


def downgrade() -> None:
    op.add_column(
        "platform_trial_settings",
        sa.Column("credit_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "platform_trial_settings",
        sa.Column("agent_limit", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        f"""
        UPDATE platform_trial_settings SET
            credit_usd = tier.one_time_credit_usd,
            agent_limit = tier.agent_limit
        FROM tier WHERE tier.id = '{FREE_TIER_ID}'
        """
    )
    op.alter_column("platform_trial_settings", "credit_usd", server_default=None)
    op.create_check_constraint(
        "ck_platform_trial_settings_credit_non_negative", "platform_trial_settings", "credit_usd >= 0"
    )
    op.create_check_constraint(
        "ck_platform_trial_settings_agent_limit_positive", "platform_trial_settings", "agent_limit >= 1"
    )
    op.create_check_constraint(
        "ck_platform_trial_settings_signup_credit",
        "platform_trial_settings",
        "NOT self_signup_enabled OR credit_usd > 0",
    )
    op.execute(f"UPDATE organization SET tier_id = NULL WHERE is_trial AND tier_id = '{FREE_TIER_ID}'")
    op.drop_column("organization", "tier_holds_due_at")
