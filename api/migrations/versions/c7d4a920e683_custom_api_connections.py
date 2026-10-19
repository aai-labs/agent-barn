"""Named Agent Custom API connections with independent isolation intent.

Revision ID: c7d4a920e683
Revises: b3d8e1f4a6c2
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d4a920e683"
down_revision = "b3d8e1f4a6c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_api_connection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("isolated", sa.Boolean(), nullable=False),
        sa.Column("credentials_encrypted", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=True),
        sa.Column("generation", sa.Uuid(), nullable=True),
        sa.UniqueConstraint("agent_id", "slug", name="uq_custom_api_connection_slug"),
    )
    op.create_index("ix_custom_api_connection_agent_id", "custom_api_connection", ["agent_id"])


def downgrade() -> None:
    op.drop_table("custom_api_connection")
