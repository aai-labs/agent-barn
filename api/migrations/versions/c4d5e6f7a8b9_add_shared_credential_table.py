"""add shared credential table and agent_secret reference

Revision ID: c4d5e6f7a8b9
Revises: a7b8c9d0e1f2
Create Date: 2026-07-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create shared_credential table
    op.create_table(
        "shared_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_shared_credential_org_name"),
    )
    op.create_index(
        "ix_shared_credential_organization_id",
        "shared_credential",
        ["organization_id"],
    )

    # 2. Add shared_credential_id to agent_secret
    op.add_column(
        "agent_secret",
        sa.Column(
            "shared_credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_secret_shared_credential",
        "agent_secret",
        "shared_credential",
        ["shared_credential_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 3. Make agent_secret.content nullable
    op.alter_column("agent_secret", "content", existing_type=sa.Text(), nullable=True)

    # 4. Add CHECK constraint: exactly one of content or shared_credential_id must be set
    op.create_check_constraint(
        "ck_agent_secret_content_xor_shared",
        "agent_secret",
        "(shared_credential_id IS NULL AND content IS NOT NULL) OR "
        "(shared_credential_id IS NOT NULL AND content IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_secret_content_xor_shared", "agent_secret", type_="check")
    op.alter_column("agent_secret", "content", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("fk_agent_secret_shared_credential", "agent_secret", type_="foreignkey")
    op.drop_column("agent_secret", "shared_credential_id")
    op.drop_index("ix_shared_credential_organization_id", table_name="shared_credential")
    op.drop_table("shared_credential")
