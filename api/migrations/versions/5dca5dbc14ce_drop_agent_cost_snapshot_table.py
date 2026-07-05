"""drop_agent_cost_snapshot_table

Revision ID: 5dca5dbc14ce
Revises: 9421ae35fdcb
Create Date: 2026-07-05 13:17:35.691570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dca5dbc14ce'
down_revision: Union[str, None] = '9421ae35fdcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_agent_cost_snapshot_snapshotted_at', table_name='agent_cost_snapshot')
    op.drop_index('ix_agent_cost_snapshot_organization_id', table_name='agent_cost_snapshot')
    op.drop_index('ix_agent_cost_snapshot_agent_id', table_name='agent_cost_snapshot')
    op.drop_table('agent_cost_snapshot')


def downgrade() -> None:
    pass
