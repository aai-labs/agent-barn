"""billing payments setting

Revision ID: 7b3b00d8227d
Revises: 218e1241a0c5
Create Date: 2026-10-19 12:15:28.426665

Whether Organizations on credit can buy more becomes a platform billing setting (AF-381),
replacing the PAYMENTS_ENABLED deployment variable. Off until a Platform Administrator
turns it on.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3b00d8227d"
down_revision: str | Sequence[str] | None = "218e1241a0c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_billing_settings",
        sa.Column("payments_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("platform_billing_settings", "payments_enabled")
