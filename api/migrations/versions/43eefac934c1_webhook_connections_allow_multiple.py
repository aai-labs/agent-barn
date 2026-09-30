"""allow multiple active webhook Connections per Agent

Revision ID: 43eefac934c1
Revises: 396d82ade4b7
Create Date: 2026-09-17 00:00:00.000000

Replaces the platform-keyed unique index with one on a new nullable singleton_key: a copy of
platform_key for every Platform except webhook, NULL for webhook. NULLs are distinct in a
unique index, so webhook Connections are unconstrained and every other Platform keeps one
active Connection per Agent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "43eefac934c1"
down_revision: str | Sequence[str] | None = "396d82ade4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communication_connection",
        sa.Column("singleton_key", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text("UPDATE communication_connection SET singleton_key = platform_key WHERE platform_key <> 'webhook'")
    )
    op.drop_index("uq_communication_connection_active_platform", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_singleton",
        "communication_connection",
        ["agent_id", "singleton_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )


def downgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*) FROM (
                    SELECT 1 FROM communication_connection
                    WHERE retired_at IS NULL
                    GROUP BY agent_id, platform_key
                    HAVING count(*) > 1
                ) AS duplicated
                """
            )
        )
        .scalar_one()
    )
    if duplicates:
        # Choosing which Connection to retire is an operator decision, not a migration's.
        raise RuntimeError(
            f"{duplicates} Agent/Platform pairs have several active Communication Connections; "
            "remove the extras before downgrading"
        )
    op.drop_index("uq_communication_connection_active_singleton", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_platform",
        "communication_connection",
        ["agent_id", "platform_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.drop_column("communication_connection", "singleton_key")
