"""add playbook_extraction table

Revision ID: 5ae205b73312
Revises: aea750215df8
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5ae205b73312"
down_revision: str | None = "aea750215df8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

playbook_extraction_status_enum = postgresql.ENUM(
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    name="playbookextractionstatus",
    create_type=False,
)


def upgrade() -> None:
    playbook_extraction_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "playbook_extraction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_name", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_sessions", sa.Integer(), nullable=False),
        sa.Column("status", playbook_extraction_status_enum, server_default="QUEUED", nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("session_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("memory_count", sa.Integer(), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("result_markdown", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_playbook_extraction_source_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by_membership_id"], ["user_organization.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="SET NULL"),
        sa.CheckConstraint("window_end > window_start", name="ck_playbook_extraction_window"),
        sa.CheckConstraint("max_sessions BETWEEN 1 AND 50", name="ck_playbook_extraction_max_sessions"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playbook_extraction_agent_created",
        "playbook_extraction",
        ["source_agent_id", "created_at"],
    )
    op.create_index("ix_playbook_extraction_skill", "playbook_extraction", ["skill_id"])
    op.create_index(
        "uq_playbook_extraction_active_agent",
        "playbook_extraction",
        ["source_agent_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"),
    )


def downgrade() -> None:
    op.drop_index("uq_playbook_extraction_active_agent", table_name="playbook_extraction")
    op.drop_index("ix_playbook_extraction_skill", table_name="playbook_extraction")
    op.drop_index("ix_playbook_extraction_agent_created", table_name="playbook_extraction")
    op.drop_table("playbook_extraction")
    playbook_extraction_status_enum.drop(op.get_bind(), checkfirst=True)
