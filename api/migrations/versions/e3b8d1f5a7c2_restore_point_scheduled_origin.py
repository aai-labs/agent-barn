"""restore point scheduled origin

Revision ID: e3b8d1f5a7c2
Revises: c7d2e9f4a1b3
Create Date: 2026-10-27 12:00:00.000000

Restore points the schedule takes on its own (AF-401).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b8d1f5a7c2"
down_revision: str | Sequence[str] | None = "c7d2e9f4a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE restorepointorigin ADD VALUE IF NOT EXISTS 'SCHEDULED'"))


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE, so 'SCHEDULED' stays on restorepointorigin.
    pass
