"""merge honcho memory pools and self-service spend limits

Revision ID: 950b3e66140a
Revises: d7a2c4f81b36, f0ad44f45ed7
Create Date: 2026-09-29 13:20:46.500517

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "950b3e66140a"
down_revision: str | Sequence[str] | None = ("d7a2c4f81b36", "f0ad44f45ed7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
