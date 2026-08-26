"""merge agent settings and skills-v2 heads

Revision ID: a17857e799a1
Revises: 04088157c78c, c7a41f8b2d93
Create Date: 2026-08-21 15:13:28.340129

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a17857e799a1"
down_revision: str | Sequence[str] | None = ("04088157c78c", "c7a41f8b2d93")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
