"""merge heads after taking staging

The platform capacity limits (AF-170) and the self-service spend limits (AF-337) each
added a migration on top of the same head. Neither touches the other's tables.

Revision ID: 6c0751e87ef1
Revises: c7a1e4b92d58, d7a2c4f81b36
Create Date: 2026-10-02

"""

from collections.abc import Sequence

revision: str = "6c0751e87ef1"
down_revision: str | Sequence[str] | None = ("c7a1e4b92d58", "d7a2c4f81b36")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
