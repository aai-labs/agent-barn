"""add Agent Task Files, each a pinned Artifact

Adds `agent_task_file`. A File points at an Artifact the Agent published and copies its
name, type and size; the bytes stay in Artifact storage. See
docs/adr/2026-10-21-native-agent-task-store.md.

Revision ID: e8b3f1a2c4d5
Revises: c41a7e2d9b10
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8b3f1a2c4d5"
down_revision: str | Sequence[str] | None = "c41a7e2d9b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_task_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id", "organization_id"],
            ["agent_task.id", "agent_task.organization_id"],
            name="fk_agent_task_file_task_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifact.id"]),
        sa.UniqueConstraint("task_id", "artifact_id", name="uq_agent_task_file_task_artifact"),
    )
    op.create_index("ix_agent_task_file_organization", "agent_task_file", ["organization_id"])
    op.create_index("ix_agent_task_file_artifact_id", "agent_task_file", ["artifact_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_task_file_artifact_id", table_name="agent_task_file")
    op.drop_index("ix_agent_task_file_organization", table_name="agent_task_file")
    op.drop_table("agent_task_file")
