"""add self-service spend limits

An Organization's own limit below the platform ceiling, a default limit for its
Agents, a limit per Agent, and the permission that lets an Organization manage them.

Every Organization without a ceiling is given the deployment default: from here on
nobody is uncapped, and the ceiling can no longer be cleared.

Revision ID: d7a2c4f81b36
Revises: 73e85ce78653
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from api.core.config import get_config

revision: str = "d7a2c4f81b36"
down_revision: str | Sequence[str] | None = "73e85ce78653"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the catalogue in code says later.
LLM_BUDGET_MANAGE_ID = UUID("5d0c2b7e-8f41-5a6c-9e3d-1b7f4a2c6e90")
LLM_BUDGET_MANAGE_KEY = "llm_budget.manage"
DEFAULT_BUDGET_DURATION = "30d"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.add_column("organization", sa.Column("llm_own_budget_usd", sa.Float(), nullable=True))
    op.get_bind().execute(
        sa.text(
            "UPDATE organization SET llm_budget_usd = :budget, llm_budget_duration = :duration "
            "WHERE llm_budget_usd IS NULL"
        ),
        {"budget": get_config().organization_default_llm_budget_usd, "duration": DEFAULT_BUDGET_DURATION},
    )
    # A ceiling set before the window became mandatory kept it NULL only while uncapped,
    # but a hand-edited row could still carry an amount without one.
    op.get_bind().execute(
        sa.text("UPDATE organization SET llm_budget_duration = :duration WHERE llm_budget_duration IS NULL"),
        {"duration": DEFAULT_BUDGET_DURATION},
    )
    op.alter_column("organization", "llm_budget_usd", existing_type=sa.Float(), nullable=False)
    op.alter_column("organization", "llm_budget_duration", existing_type=sa.String(length=32), nullable=False)
    op.create_check_constraint(
        "check_llm_own_budget_within_ceiling",
        "organization",
        "llm_own_budget_usd IS NULL OR (llm_own_budget_usd >= 0 AND llm_own_budget_usd <= llm_budget_usd)",
    )

    op.add_column(
        "organization_agent_settings",
        sa.Column("default_agent_llm_budget_usd", sa.Float(), nullable=True),
    )
    op.create_check_constraint(
        "check_default_agent_llm_budget_non_negative",
        "organization_agent_settings",
        "default_agent_llm_budget_usd IS NULL OR default_agent_llm_budget_usd >= 0",
    )

    # NULL follows the Organization's default, so existing Agents need no backfill.
    op.add_column("agent", sa.Column("llm_budget_usd", sa.Float(), nullable=True))
    op.create_check_constraint(
        "check_agent_llm_budget_non_negative", "agent", "llm_budget_usd IS NULL OR llm_budget_usd >= 0"
    )
    op.add_column("agent", sa.Column("llm_spend_usd", sa.Float(), nullable=True))
    op.add_column("agent", sa.Column("llm_spend_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent", sa.Column("llm_budget_renews_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent", sa.Column("llm_alerted_threshold", sa.Integer(), nullable=True))
    op.add_column("agent", sa.Column("llm_alert_key", sa.String(length=128), nullable=True))

    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=LLM_BUDGET_MANAGE_ID,
        key=LLM_BUDGET_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=LLM_BUDGET_MANAGE_ID)

    for column in (
        "llm_alert_key",
        "llm_alerted_threshold",
        "llm_budget_renews_at",
        "llm_spend_observed_at",
        "llm_spend_usd",
    ):
        op.drop_column("agent", column)
    op.drop_constraint("check_agent_llm_budget_non_negative", "agent", type_="check")
    op.drop_column("agent", "llm_budget_usd")

    op.drop_constraint("check_default_agent_llm_budget_non_negative", "organization_agent_settings", type_="check")
    op.drop_column("organization_agent_settings", "default_agent_llm_budget_usd")

    op.drop_constraint("check_llm_own_budget_within_ceiling", "organization", type_="check")
    op.drop_column("organization", "llm_own_budget_usd")
    # The backfilled ceilings stay: they are real limits now enforced by the proxy, and
    # clearing them here would silently uncap every Organization that had none.
    op.alter_column("organization", "llm_budget_duration", existing_type=sa.String(length=32), nullable=True)
    op.alter_column("organization", "llm_budget_usd", existing_type=sa.Float(), nullable=True)
