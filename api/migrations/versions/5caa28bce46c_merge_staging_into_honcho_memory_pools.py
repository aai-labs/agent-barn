"""merge staging into honcho memory pools

Revision ID: 5caa28bce46c
Revises: 025d51054354, c3b7e19d4a52
Create Date: 2026-09-23 12:59:56.451896

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5caa28bce46c"
down_revision: str | Sequence[str] | None = ("025d51054354", "c3b7e19d4a52")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
