"""remove Discord Connection require mention

Revision ID: 16ac819db080
Revises: 00cdd18a6e91
Create Date: 2026-10-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision: str = "16ac819db080"
down_revision: str | None = "00cdd18a6e91"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET settings = (settings::jsonb - 'require_mention')::json,
                schema_version = 3
            WHERE platform_key = 'discord'
            """
        )
    )


def downgrade() -> None:
    # Discord now always requires a mention, so only the former default can be restored.
    op.execute(
        sa.text(
            """
            UPDATE communication_connection
            SET settings = (settings::jsonb || '{"require_mention": true}'::jsonb)::json,
                schema_version = 2
            WHERE platform_key = 'discord'
            """
        )
    )
