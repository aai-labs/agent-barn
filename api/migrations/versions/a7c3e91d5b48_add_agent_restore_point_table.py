"""add agent_restore_point table

Revision ID: a7c3e91d5b48
Revises: b3d1f47c9a20
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c3e91d5b48"
down_revision: str | None = "b3d1f47c9a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_CAPTURE_PREDICATE = "status IN ('PENDING', 'CAPTURING')"

restore_point_status_enum = postgresql.ENUM(
    "PENDING",
    "CAPTURING",
    "RESTORING",
    "READY",
    "FAILED",
    "DELETING",
    name="restorepointstatus",
    create_type=False,
)

restore_point_origin_enum = postgresql.ENUM(
    "MANUAL",
    "PRE_RESTORE",
    "PRE_RESET",
    "PRE_UPGRADE",
    name="restorepointorigin",
    create_type=False,
)


def upgrade() -> None:
    restore_point_status_enum.create(op.get_bind(), checkfirst=True)
    restore_point_origin_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_restore_point",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("status", restore_point_status_enum, server_default="PENDING", nullable=False),
        sa.Column("origin", restore_point_origin_enum, server_default="MANUAL", nullable=False),
        sa.Column("agent_type", sa.String(length=20), nullable=False),
        sa.Column("pvc_name", sa.String(length=253), nullable=False),
        sa.Column("job_name", sa.String(length=253), nullable=True),
        sa.Column("archive_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("config_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_restore_point_agent_created",
        "agent_restore_point",
        ["agent_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "uq_agent_restore_point_active_capture",
        "agent_restore_point",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_CAPTURE_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_restore_point_active_capture", table_name="agent_restore_point")
    op.drop_index("ix_agent_restore_point_agent_created", table_name="agent_restore_point")
    op.drop_table("agent_restore_point")
    restore_point_origin_enum.drop(op.get_bind(), checkfirst=True)
    restore_point_status_enum.drop(op.get_bind(), checkfirst=True)
