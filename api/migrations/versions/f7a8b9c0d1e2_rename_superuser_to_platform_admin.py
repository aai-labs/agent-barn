"""rename superuser flag to platform admin

Revision ID: f7a8b9c0d1e2
Revises: e6b7c8d9e0f1
Create Date: 2026-07-28 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_user_is_superuser", table_name="user")
    op.alter_column("user", "is_superuser", new_column_name="is_platform_admin")
    op.create_index("ix_user_is_platform_admin", "user", ["is_platform_admin"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_is_platform_admin", table_name="user")
    op.alter_column("user", "is_platform_admin", new_column_name="is_superuser")
    op.create_index("ix_user_is_superuser", "user", ["is_superuser"], unique=False)
