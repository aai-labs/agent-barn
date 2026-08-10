"""merge heads

Revision ID: ee8815d37c1c
Revises: 96333a5d58e4, f1f5643dc699
Create Date: 2026-08-04 14:44:11.317086

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ee8815d37c1c"
down_revision: str | Sequence[str] | None = ("96333a5d58e4", "f1f5643dc699")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
