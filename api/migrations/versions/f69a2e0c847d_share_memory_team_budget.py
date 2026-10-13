"""Share Organization team budgets with memory processing and index memory charges.

Revision ID: f69a2e0c847d
Revises: e94b17c62a30
"""

import sqlalchemy as sa
from alembic import op

revision = "f69a2e0c847d"
down_revision = "e94b17c62a30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_memory_key",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_encrypted", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("organization_id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(
        "ix_cost_record_memory_org_occurred",
        "cost_record",
        ["organization_id", "occurred_at"],
        postgresql_where=sa.text("is_memory IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_cost_record_memory_org_occurred", table_name="cost_record")
    op.drop_table("organization_memory_key")
