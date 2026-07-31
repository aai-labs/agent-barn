"""make agent template pin nullable

Revision ID: e7a4b9c2d5f1
Revises: d3f9a1c7b2e5
Create Date: 2026-07-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a4b9c2d5f1"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deleting a template lineage detaches soft-deleted agents by NULLing their
    # pin; with a NULL column the composite RESTRICT FK is no longer enforced.
    op.alter_column("agent", "template_slug", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("agent", "template_version", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Fails if any agent row has a NULL pin (detached by a template deletion).
    op.alter_column("agent", "template_version", existing_type=sa.Integer(), nullable=False)
    op.alter_column("agent", "template_slug", existing_type=sa.String(length=255), nullable=False)
