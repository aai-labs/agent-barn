"""add cost record table

Revision ID: c3f1a7d2e9b4
Revises: 87ec190e0f7d
Create Date: 2026-09-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f1a7d2e9b4"
down_revision: str | Sequence[str] | None = "87ec190e0f7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Must stay identical to HEAL_CANDIDATE_PREDICATE in api/domains/costs/models.py.
# The healing query filters on exactly this, so a drift here quietly costs us the
# index scan on a table that grows by every LLM call the platform makes.
_HEAL_CANDIDATE_PREDICATE = "spend = 0 AND status = 'success' AND total_tokens > 0 AND source = 'litellm_live'"


def upgrade() -> None:
    # agent_id and organization_id carry no foreign keys on purpose. Cost history
    # is financial record-keeping and has to outlive the rows it points at, so the
    # display names are captured at write time instead of joined at read time.
    op.create_table(
        "cost_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("litellm_key_hash", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spend", sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("call_type", sa.String(length=64), nullable=True),
        sa.Column("request_duration_ms", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("agent_name", sa.String(length=255), nullable=True),
        sa.Column("organization_name", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("healed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_cost_record_request_id"),
    )
    op.create_index(
        "ix_cost_record_org_occurred",
        "cost_record",
        ["organization_id", "occurred_at"],
    )
    op.create_index(
        "ix_cost_record_agent_occurred",
        "cost_record",
        ["agent_id", "occurred_at"],
    )
    op.create_index(
        "ix_cost_record_occurred_at",
        "cost_record",
        ["occurred_at"],
    )
    op.create_index(
        "ix_cost_record_heal_candidates",
        "cost_record",
        ["occurred_at"],
        postgresql_where=sa.text(_HEAL_CANDIDATE_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("ix_cost_record_heal_candidates", table_name="cost_record")
    op.drop_index("ix_cost_record_occurred_at", table_name="cost_record")
    op.drop_index("ix_cost_record_agent_occurred", table_name="cost_record")
    op.drop_index("ix_cost_record_org_occurred", table_name="cost_record")
    op.drop_table("cost_record")
