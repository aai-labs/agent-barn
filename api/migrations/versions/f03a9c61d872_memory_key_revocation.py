"""Queue remote memory credential cleanup independently of Organization lifetime."""

import sqlalchemy as sa
from alembic import op

revision = "f03a9c61d872"
down_revision = "e81c2a97b4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_key_revocation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index(
        "ix_memory_key_revocation_pending",
        "memory_key_revocation",
        ["updated_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_key_revocation_pending", table_name="memory_key_revocation")
    op.drop_table("memory_key_revocation")
