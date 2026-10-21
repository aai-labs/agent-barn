"""add Agent Tasks, their Notes and Files

Adds `agent_task`, `agent_task_note`, `agent_task_file` and the Postgres file store's
`agent_task_file_chunk`. See docs/adr/2026-10-21-native-agent-task-store.md.

Revision ID: b7d4e1a9c362
Revises: a4e9c2d7b615
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e1a9c362"
down_revision: str | Sequence[str] | None = "a4e9c2d7b615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_task_status_enum = postgresql.ENUM(
    "open", "in_progress", "done", "failed", name="agenttaskstatus", create_type=False
)


def upgrade() -> None:
    agent_task_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", agent_task_status_enum, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_task_agent_organization",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_agent_task_organization_agent_created",
        "agent_task",
        ["organization_id", "agent_id", "created_at"],
    )
    op.create_index("ix_agent_task_organization_status", "agent_task", ["organization_id", "status"])

    op.create_table(
        "agent_task_note",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_task.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_task_note_task_created", "agent_task_note", ["task_id", "created_at"])

    op.create_table(
        "agent_task_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["agent_task.id"], ondelete="CASCADE"),
        sa.CheckConstraint("size_bytes > 0", name="ck_agent_task_file_size_positive"),
    )
    op.create_index("ix_agent_task_file_task", "agent_task_file", ["task_id"])
    op.create_index("ix_agent_task_file_organization", "agent_task_file", ["organization_id"])

    op.create_table(
        "agent_task_file_chunk",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("file_id", "sequence"),
        sa.ForeignKeyConstraint(["file_id"], ["agent_task_file.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("agent_task_file_chunk")
    op.drop_index("ix_agent_task_file_organization", table_name="agent_task_file")
    op.drop_index("ix_agent_task_file_task", table_name="agent_task_file")
    op.drop_table("agent_task_file")
    op.drop_index("ix_agent_task_note_task_created", table_name="agent_task_note")
    op.drop_table("agent_task_note")
    op.drop_index("ix_agent_task_organization_status", table_name="agent_task")
    op.drop_index("ix_agent_task_organization_agent_created", table_name="agent_task")
    op.drop_table("agent_task")
    agent_task_status_enum.drop(op.get_bind(), checkfirst=True)
