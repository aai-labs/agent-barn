"""Merge workflow authoring and staging migration heads.

Revision ID: c32e42bb0396
Revises: a38802d7f002, d72b85f19c40
"""

revision: str = "c32e42bb0396"
down_revision: tuple[str, str] = ("a38802d7f002", "d72b85f19c40")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
