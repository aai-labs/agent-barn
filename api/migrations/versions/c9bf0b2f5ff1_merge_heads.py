"""merge heads

Revision ID: c9bf0b2f5ff1
Revises: 39d76e561f6d, a4b5c6d7e8f9
Create Date: 2026-09-06 22:53:53.797146

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c9bf0b2f5ff1"
down_revision: str | Sequence[str] | None = ("39d76e561f6d", "a4b5c6d7e8f9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
