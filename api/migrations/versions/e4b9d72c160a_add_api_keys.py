"""Add personal API keys.

Revision ID: e4b9d72c160a
Revises: 73e85ce78653
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4b9d72c160a"
down_revision = "73e85ce78653"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("access_mode", sa.Enum("READ_ONLY", "FULL", name="apikeyaccessmode"), nullable=False),
        sa.Column("security_stamp", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_api_key_token_hash", "api_key", ["token_hash"], unique=True)
    op.create_index("ix_api_key_user_created", "api_key", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_api_key_user_created", table_name="api_key")
    op.drop_index("uq_api_key_token_hash", table_name="api_key")
    op.drop_table("api_key")
    sa.Enum(name="apikeyaccessmode").drop(op.get_bind())
