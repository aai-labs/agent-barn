"""add agent email addresses

Revision ID: c4e7a1b93f26
Revises: 87ec190e0f7d
Create Date: 2026-08-31 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e7a1b93f26"
down_revision: str | Sequence[str] | None = "87ec190e0f7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_email_address",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("local_part", sa.String(length=128), nullable=False),
        sa.Column("address", sa.String(length=254), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "organization_id"],
            ["communication_connection.id", "communication_connection.organization_id"],
            name="fk_agent_email_address_connection_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("connection_id", name="uq_agent_email_address_connection"),
    )
    op.create_index(
        "uq_agent_email_address_local_part",
        "agent_email_address",
        [sa.text("lower(local_part)")],
        unique=True,
    )
    op.create_index("ix_agent_email_address_agent", "agent_email_address", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_email_address_agent", table_name="agent_email_address")
    op.drop_index("uq_agent_email_address_local_part", table_name="agent_email_address")
    op.drop_table("agent_email_address")
