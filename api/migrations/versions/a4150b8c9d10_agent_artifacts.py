"""Shared immutable Agent artifacts and durable reference/cleanup metadata.

Revision ID: a4150b8c9d10
Revises: f8740a67b788
"""

import sqlalchemy as sa
from alembic import op

revision = "a4150b8c9d10"
down_revision = "f8740a67b788"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "artifact",
        *base_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("bucket", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_id", sa.Uuid()),
        sa.Column("run_id", sa.Uuid()),
        sa.Column("step_id", sa.Uuid()),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("generation", sa.Integer()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("purge_attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("state IN ('UPLOADING','READY','DELETING','DELETED')", name="ck_artifact_state"),
        sa.CheckConstraint("size >= 0", name="ck_artifact_size"),
    )
    for name in ("organization_id", "agent_id", "expires_at", "run_id"):
        op.create_index(f"ix_artifact_{name}", "artifact", [name])
    op.create_table(
        "artifact_reference",
        *base_columns(),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("artifact_id", "kind", "owner_id", name="uq_artifact_reference"),
    )
    for name in ("artifact_id", "owner_id"):
        op.create_index(f"ix_artifact_reference_{name}", "artifact_reference", [name])


def downgrade() -> None:
    # Never discard the only record of private bytes that still need purging.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM artifact WHERE state != 'DELETED' LIMIT 1")).first():
        raise RuntimeError("Purge retained artifact bytes before downgrading AF-415")
    op.drop_table("artifact_reference")
    op.drop_table("artifact")
