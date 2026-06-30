"""add models_breakdown_json

Revision ID: 849e21682b7a
Revises: 777879d0a4c9
Create Date: 2026-06-29 14:17:39.552516

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "849e21682b7a"
down_revision: Union[str, None] = "777879d0a4c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_cost_snapshot",
        sa.Column(
            "models_breakdown_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_cost_snapshot", "models_breakdown_json")
