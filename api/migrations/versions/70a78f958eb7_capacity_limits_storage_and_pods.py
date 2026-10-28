"""Add the requests.storage and pods quota ceilings

Revision ID: 70a78f958eb7
Revises: a4e9c2d7b615
Create Date: 2026-10-20

The namespace's ResourceQuota caps the storage every volume claim requests and the number of
pods, as well as CPU and memory, and a full storage quota left a new agent without its volume
(AF-266). The environment health page compares these two ceilings with the claims and pods the
API lists itself, so a Platform Administrator enters them as they do the other four. Both start
empty, which means "no limit entered", so nothing warns until someone sets them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "70a78f958eb7"
down_revision: str | Sequence[str] | None = "a4e9c2d7b615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_resource_limits"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("requests_storage_bytes", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("pods", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "pods")
    op.drop_column(_TABLE, "requests_storage_bytes")
