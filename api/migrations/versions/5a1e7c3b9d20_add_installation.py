"""Add the Installation identity.

Revision ID: 5a1e7c3b9d20
Revises: c055b65baf67
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5a1e7c3b9d20"
down_revision = "c055b65baf67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installation",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("singleton", name="ck_installation_singleton"),
    )
    op.execute("INSERT INTO installation (singleton) VALUES (true)")


def downgrade() -> None:
    op.drop_table("installation")
