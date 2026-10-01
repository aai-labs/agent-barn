"""add business_action table

Revision ID: 39ea6a8e2fe4
Revises: 73e85ce78653
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "39ea6a8e2fe4"
down_revision: str | None = "73e85ce78653"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

business_action_status_enum = postgresql.ENUM(
    "SUCCESS", "ERROR", "UNKNOWN", name="businessactionstatus", create_type=False
)


def upgrade() -> None:
    business_action_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "business_action",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("integration", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("verb", sa.Text(), nullable=False),
        sa.Column("outcome_type", sa.String(length=64), nullable=True),
        sa.Column("is_write", sa.Boolean(), nullable=True),
        sa.Column("status", business_action_status_enum, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_call.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id", "ordinal", name="uq_business_action_tool_call_ordinal"),
    )
    op.create_index(
        "ix_business_action_organization_occurred",
        "business_action",
        ["organization_id", "occurred_at"],
    )
    op.create_index("ix_business_action_agent_occurred", "business_action", ["agent_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_business_action_agent_occurred", table_name="business_action")
    op.drop_index("ix_business_action_organization_occurred", table_name="business_action")
    op.drop_table("business_action")
    business_action_status_enum.drop(op.get_bind(), checkfirst=True)
