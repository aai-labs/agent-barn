"""restore point changed file counts

Revision ID: 8946864ecb73
Revises: 9cea829832b8
Create Date: 2026-11-03 13:08:27.000000

How many files shrank or vanished while a live capture read them (AF-401). The
capture Job already wrote both counts to its manifest; nothing kept them.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8946864ecb73"
down_revision: str | Sequence[str] | None = "9cea829832b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_restore_point", sa.Column("changed_file_count", sa.Integer(), nullable=True))
    op.add_column("agent_restore_point", sa.Column("skipped_file_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_restore_point", "skipped_file_count")
    op.drop_column("agent_restore_point", "changed_file_count")
