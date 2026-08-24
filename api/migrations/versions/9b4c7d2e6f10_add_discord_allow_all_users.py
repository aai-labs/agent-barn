"""add Discord allow-all-users policy

Revision ID: 9b4c7d2e6f10
Revises: 04088157c78c
Create Date: 2026-08-22

"""

import sqlalchemy as sa
from alembic import op

revision: str = "9b4c7d2e6f10"
down_revision: str | None = "04088157c78c"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent_discord_config",
        sa.Column("allow_all_users", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        sa.text(
            "UPDATE agent_discord_config "
            "SET allow_all_users = false "
            "WHERE EXISTS ("
            "SELECT 1 FROM json_array_elements_text(allowed_user_ids) AS user_id "
            "WHERE btrim(user_id) <> ''"
            ") OR EXISTS ("
            "SELECT 1 FROM json_array_elements_text(allowed_role_ids) AS role_id "
            "WHERE btrim(role_id) <> ''"
            ")"
        )
    )


def downgrade() -> None:
    op.drop_column("agent_discord_config", "allow_all_users")
