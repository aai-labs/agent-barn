"""drop billing credit rate

Revision ID: 6553916224ec
Revises: 7b3b00d8227d
Create Date: 2026-10-19 14:49:36.131542

$1 of credit is always $1 of model spend (AF-381): the purchase fee is the only markup,
so the credit rate setting goes. AF-381 hasn't been deployed, so no stored rate is lost;
a downgrade restores the column at 1.0, selling at cost.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6553916224ec"
down_revision: str | Sequence[str] | None = "7b3b00d8227d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_platform_billing_settings_rate_positive", "platform_billing_settings", type_="check")
    op.drop_column("platform_billing_settings", "credit_rate")


def downgrade() -> None:
    op.add_column(
        "platform_billing_settings",
        sa.Column("credit_rate", sa.Float(), server_default=sa.text("1.0"), nullable=False),
    )
    op.alter_column("platform_billing_settings", "credit_rate", server_default=None)
    op.create_check_constraint(
        "ck_platform_billing_settings_rate_positive", "platform_billing_settings", "credit_rate > 0"
    )
