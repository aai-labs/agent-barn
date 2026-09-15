"""remove Slack Connection verbose mode

Revision ID: c4e8a2f19d73
Revises: a7c3e91d5b48
Create Date: 2026-09-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f19d73"
down_revision: str | None = "a7c3e91d5b48"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET settings = (settings::jsonb - 'verbose_mode')::json,
                schema_version = 2
            WHERE platform_key = 'slack'
            """
        )
    )


def downgrade() -> None:
    # The removed per-Connection choice had no runtime consumer, so only its
    # former default can be restored.
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET settings = (settings::jsonb || '{"verbose_mode": true}'::jsonb)::json,
                schema_version = 1
            WHERE platform_key = 'slack'
            """
        )
    )
