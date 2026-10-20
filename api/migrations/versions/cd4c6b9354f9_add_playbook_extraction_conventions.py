"""Keep the Organization Conventions a Playbook Extraction proposes.

Revision ID: cd4c6b9354f9
Revises: a77ac74c3fad
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "cd4c6b9354f9"
down_revision = "a77ac74c3fad"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "playbook_extraction",
        sa.Column(
            "result_conventions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade():
    op.drop_column("playbook_extraction", "result_conventions")
