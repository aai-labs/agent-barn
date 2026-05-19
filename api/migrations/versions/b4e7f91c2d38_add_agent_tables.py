"""add agent tables

Revision ID: b4e7f91c2d38
Revises: 8f3c2a7d9b10
Create Date: 2026-05-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e7f91c2d38"
down_revision: Union[str, None] = "8f3c2a7d9b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

agent_status_enum = postgresql.ENUM(
    "STOPPED", "RUNNING", "ERROR", name="agentstatus", create_type=False
)


def upgrade() -> None:
    agent_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("identity_md", sa.Text(), nullable=False),
        sa.Column("user_md", sa.Text(), nullable=False),
        sa.Column("tools_md", sa.Text(), nullable=False),
        sa.Column("agents_md", sa.Text(), nullable=False),
        sa.Column("boot_md", sa.Text(), nullable=False),
        sa.Column("bootstrap_md", sa.Text(), nullable=False),
        sa.Column("heartbeat_md", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_template_organization_id", "agent_template", ["organization_id"]
    )

    op.create_table(
        "agent",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slack_bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("slack_app_token_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "status",
            agent_status_enum,
            nullable=False,
            server_default="STOPPED",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["agent_template.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_organization_deleted", "agent", ["organization_id", "deleted_at"]
    )
    op.create_index("ix_agent_status", "agent", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_status", table_name="agent")
    op.drop_index("ix_agent_organization_deleted", table_name="agent")
    op.drop_table("agent")

    op.drop_index("ix_agent_template_organization_id", table_name="agent_template")
    op.drop_table("agent_template")

    agent_status_enum.drop(op.get_bind(), checkfirst=True)
