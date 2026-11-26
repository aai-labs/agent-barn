"""Add whether an Organization emails its unusual activity alerts

Revision ID: 4010f1f2d1f1
Revises: 2180817c8927
Create Date: 2026-11-26

An Organization's Owners and Admins may keep detection on and stop the emails. Alerts
are on unless turned off, so existing Organizations keep getting them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4010f1f2d1f1"
down_revision: str | Sequence[str] | None = "2180817c8927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_anomaly_settings",
        sa.Column("alerts_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("organization_anomaly_settings", "alerts_enabled")
