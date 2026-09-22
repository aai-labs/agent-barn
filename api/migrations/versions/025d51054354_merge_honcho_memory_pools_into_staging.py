"""merge honcho memory pools into staging

Revision ID: 025d51054354
Revises: a1f42e91843f, e4f7c2a9b103
Create Date: 2026-09-22 20:27:34.977269

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "025d51054354"
down_revision: str | Sequence[str] | None = ("a1f42e91843f", "e4f7c2a9b103")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
