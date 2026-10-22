"""Merge workflow authoring and playbook staging migration heads.

Revision ID: 49e4d8bea6de
Revises: 517d402a59fd, c32e42bb0396
"""

revision: str = "49e4d8bea6de"
down_revision: tuple[str, str] = ("517d402a59fd", "c32e42bb0396")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
