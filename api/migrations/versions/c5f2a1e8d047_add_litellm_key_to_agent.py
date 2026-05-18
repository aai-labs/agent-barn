"""add litellm_key_encrypted to agent

Revision ID: c5f2a1e8d047
Revises: b4e7f91c2d38
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f2a1e8d047"
down_revision: Union[str, None] = "b4e7f91c2d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("litellm_key_encrypted", sa.Text(), nullable=True))
    op.execute(
        "UPDATE agent SET litellm_key_encrypted = '' WHERE litellm_key_encrypted IS NULL"
    )
    op.alter_column("agent", "litellm_key_encrypted", nullable=False)


def downgrade() -> None:
    op.drop_column("agent", "litellm_key_encrypted")
