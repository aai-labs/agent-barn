"""enforce one active Communication Connection per Platform per Agent

Revision ID: b6d4f2a8c913
Revises: c4e8a2f19d73
Create Date: 2026-09-16 00:00:00.000000

Native runtime gateways (ADR 2026-09-16) run one account per Platform, so an Agent
may no longer hold two active Connections on the same Platform. This generalizes
the Web Chat-only index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d4f2a8c913"
down_revision: str | Sequence[str] | None = "c4e8a2f19d73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
            "remove the extras before upgrading"
        )
    op.drop_index("uq_communication_connection_active_web", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_platform",
        "communication_connection",
        ["agent_id", "platform_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_communication_connection_active_platform", table_name="communication_connection")
    op.create_index(
        "uq_communication_connection_active_web",
        "communication_connection",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND platform_key = 'web'"),
    )
