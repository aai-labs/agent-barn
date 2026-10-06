"""merge heads after taking staging again

Staging merged its own heads (spend limits and API keys) while the platform capacity
limits (AF-170) were in review. This joins AF-170's merge head to staging's. Nothing here
touches any table.

Revision ID: 821ed7cce78f
Revises: 6c0751e87ef1, c055b65baf67
Create Date: 2026-10-06

"""

from collections.abc import Sequence

revision: str = "821ed7cce78f"
down_revision: str | Sequence[str] | None = ("6c0751e87ef1", "c055b65baf67")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
