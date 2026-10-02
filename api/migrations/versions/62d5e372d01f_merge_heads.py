"""merge staging (self-service spend limits) into honcho memory pools

Revision ID: 62d5e372d01f
Revises: d7a2c4f81b36, f0ad44f45ed7
Create Date: 2026-10-02 10:39:08.818611

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "62d5e372d01f"
down_revision: str | Sequence[str] | None = ("d7a2c4f81b36", "f0ad44f45ed7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
