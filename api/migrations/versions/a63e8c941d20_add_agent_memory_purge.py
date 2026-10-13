"""Queue durable Agent Memory deletion cleanup.

Revision ID: a63e8c941d20
Revises: f2a8d41b9c63
Create Date: 2026-10-04
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "a63e8c941d20"
down_revision = "f2a8d41b9c63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "agent_memory_purge",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_id", sa.Uuid()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_cleaned_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(32)),
    )
    op.create_index("ix_agent_memory_purge_due", "agent_memory_purge", ["next_attempt_at"])
    conn = op.get_bind()
    for row in conn.execute(sa.text("SELECT id, organization_id, deleted_at FROM agent WHERE deleted_at IS NOT NULL")):
        conn.execute(
            table.insert().values(
                id=uuid.uuid4(),
                agent_id=row.id,
                organization_id=row.organization_id,
                created_at=row.deleted_at,
                updated_at=row.deleted_at,
                next_attempt_at=sa.func.now(),
                attempts=0,
            )
        )
    conn.execute(
        sa.text("""DELETE FROM agent_memory_grant g USING agent a
        WHERE a.deleted_at IS NOT NULL AND (g.agent_id = a.id OR g.source_agent_id = a.id)""")
    )
    conn.execute(sa.text("UPDATE agent SET memory_key_hash = NULL WHERE deleted_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("agent_memory_purge")
