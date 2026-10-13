"""Preserve existing integration routing as dormant per-Agent policy.

Revision ID: 7f20a9c813de
Revises: e02ebff7a128
"""

import sqlalchemy as sa
from alembic import op

revision: str = "7f20a9c813de"
down_revision: str | None = "e02ebff7a128"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent_integration_isolation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("isolated", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "provider", name="uq_agent_integration_isolation"),
    )
    # Freeze history here; never import current plugins into a data migration.
    op.execute(
        """
        INSERT INTO agent_integration_isolation (id, created_at, updated_at, agent_id, provider, isolated)
        SELECT gen_random_uuid(), now(), now(), s.agent_id, s.provider,
               s.provider IN ('github', 'jira', 'confluence', 'bitbucket',
                              'pipedrive', 'firecrawl', 'google_workspace')
        FROM agent_secret s JOIN agent a ON a.id = s.agent_id
        WHERE a.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_table("agent_integration_isolation")
