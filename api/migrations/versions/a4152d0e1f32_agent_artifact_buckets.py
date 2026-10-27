"""Per-Agent private buckets and encrypted bucket-scoped credentials.

Revision ID: a4152d0e1f32
Revises: a4151c9d0e21

Fresh per-Agent layout only: no shared-bucket byte migration is performed.
"""

import sqlalchemy as sa
from alembic import op

revision = "a4152d0e1f32"
down_revision = "a4151c9d0e21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_bucket",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("access_key", sa.String(), nullable=False, unique=True),
        sa.Column("secret_key_encrypted", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), unique=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String()),
        sa.CheckConstraint("state IN ('PENDING','READY','DELETING','DELETED')", name="ck_artifact_bucket_state"),
    )
    op.create_index("ix_artifact_bucket_organization_id", "artifact_bucket", ["organization_id"])
    op.create_index("ix_artifact_bucket_retry_at", "artifact_bucket", ["retry_at"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM artifact_bucket WHERE state != 'DELETED' LIMIT 1")).first():
        raise RuntimeError("Purge per-Agent buckets and revoke their keys before downgrade")
    op.drop_table("artifact_bucket")
