"""platform provisioned users

Revision ID: b8e5f3a1c207
Revises: a7d4e2c9b816
Create Date: 2026-10-14 14:00:00.000000

Who may create Organizations on the platform's budget (AF-381). Only accounts a Platform
Administrator set up (or Platform Administrators themselves) do; everyone else's new
Organizations run on credit. Every account that exists now and did not sign itself up
counts as set up by the platform, so nobody's current behaviour changes.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e5f3a1c207"
down_revision: str | Sequence[str] | None = "a7d4e2c9b816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("platform_provisioned_at", sa.DateTime(timezone=True), nullable=True))
    op.execute('UPDATE "user" SET platform_provisioned_at = now() WHERE signed_up_at IS NULL')


def downgrade() -> None:
    op.drop_column("user", "platform_provisioned_at")
