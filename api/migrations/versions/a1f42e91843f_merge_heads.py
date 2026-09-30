"""merge heads

Revision ID: a1f42e91843f
Revises: 4b4bb4af4d31, f2b9d4c7a610

"""

from collections.abc import Sequence

revision: str = "a1f42e91843f"
down_revision: str | Sequence[str] | None = ("4b4bb4af4d31", "f2b9d4c7a610")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
