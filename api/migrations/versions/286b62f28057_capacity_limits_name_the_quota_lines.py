"""Name the capacity limits as the quota does, and add the requests ceilings

Revision ID: 286b62f28057
Revises: 69011ec264e7
Create Date: 2026-10-07

A ResourceQuota caps requests as well as limits, and a new pod is refused when any one of
them would go over, so the page needs all four ceilings (AF-170). The two columns that held
the limits ceilings are renamed after the quota's own lines (limits.memory, limits.cpu) and
two more hold requests.memory and requests.cpu. The values already saved keep their meaning:
they were typed as limits ceilings. The new columns start empty, which means "no limit
entered", so nothing warns about requests until someone sets them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "286b62f28057"
down_revision: str | Sequence[str] | None = "69011ec264e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_resource_limits"


def upgrade() -> None:
    op.alter_column(_TABLE, "memory_limit_bytes", new_column_name="limits_memory_bytes")
    op.alter_column(_TABLE, "cpu_limit_cores", new_column_name="limits_cpu_cores")
    op.add_column(_TABLE, sa.Column("requests_memory_bytes", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("requests_cpu_cores", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "requests_cpu_cores")
    op.drop_column(_TABLE, "requests_memory_bytes")
    op.alter_column(_TABLE, "limits_cpu_cores", new_column_name="cpu_limit_cores")
    op.alter_column(_TABLE, "limits_memory_bytes", new_column_name="memory_limit_bytes")
