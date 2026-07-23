"""Merge multiple heads

Revision ID: 5a1afb6a33d3
Revises: 181dcfcc93ef, a6f2c9d18e47, e1f2a3b4c5d6
Create Date: 2026-07-23 13:48:45.731696

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "5a1afb6a33d3"
down_revision: Union[str, None] = ("181dcfcc93ef", "a6f2c9d18e47", "e1f2a3b4c5d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
