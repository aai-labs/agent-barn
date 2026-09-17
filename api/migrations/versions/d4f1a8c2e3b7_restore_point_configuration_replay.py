"""record restore point configuration replay intent

Revision ID: d4f1a8c2e3b7
Revises: c4e8a2f19d73
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1a8c2e3b7"
down_revision: str | None = "a0e8c15d9e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The configuration is written only once the Job confirms the volume is back, so
    # the intent has to outlive the request that asked for it.
    op.add_column(
        "agent_restore_point",
        sa.Column("reapply_configuration", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_restore_point",
        sa.Column("configuration_error", sa.String(length=500), nullable=True),
    )
    # The deferred write belongs to whoever asked for the restore, not to whoever
    # captured the restore point — often two different people.
    op.add_column(
        "agent_restore_point",
        sa.Column("restored_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "agent_restore_point",
        sa.Column("restored_by_display", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_restore_point_restored_by_user",
        "agent_restore_point",
        "user",
        ["restored_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_restore_point_restored_by_user", "agent_restore_point", type_="foreignkey")
    op.drop_column("agent_restore_point", "restored_by_display")
    op.drop_column("agent_restore_point", "restored_by_user_id")
    op.drop_column("agent_restore_point", "configuration_error")
    op.drop_column("agent_restore_point", "reapply_configuration")
