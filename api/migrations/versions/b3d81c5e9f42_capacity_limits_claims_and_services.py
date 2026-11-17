"""Add the persistentvolumeclaims and services quota ceilings

Revision ID: b3d81c5e9f42
Revises: 38de1199ae19
Create Date: 2026-11-12

The namespace's ResourceQuota also caps how many volume claims and Services may exist, and on
staging the claim count sat at 60 of 60, so scheduled backups could not create their claims
(AF-436). The environment health page compares these two ceilings with the claims and Services
the API lists itself, as it does storage and pods. Both start empty, meaning "no limit entered".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d81c5e9f42"
down_revision: str | Sequence[str] | None = "38de1199ae19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_resource_limits"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("persistentvolumeclaims", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("services", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "services")
    op.drop_column(_TABLE, "persistentvolumeclaims")
