"""Agent-scoped outbound submission identity and one configured default.

Revision ID: c92d0eaf3101
Revises: becf34295941
"""

import sqlalchemy as sa
from alembic import op

revision = "c92d0eaf3101"
down_revision = "becf34295941"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communication_delivery", sa.Column("submission_key", sa.String(64), nullable=True))
    op.add_column("communication_delivery", sa.Column("request_digest", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_communication_delivery_submission", "communication_delivery", ["agent_id", "submission_key"]
    )
    op.create_index(
        "uq_communication_connection_default_target",
        "communication_connection",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL AND settings->>'default_delivery_target' IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_communication_connection_default_target", table_name="communication_connection")
    op.drop_constraint("uq_communication_delivery_submission", "communication_delivery", type_="unique")
    op.drop_column("communication_delivery", "request_digest")
    op.drop_column("communication_delivery", "submission_key")
