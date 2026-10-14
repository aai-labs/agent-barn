"""Preserve direct routing for Apollo credentials saved before isolation support.

Revision ID: 0d612dc60e9a
Revises: 0c180f95890c
"""

from alembic import op

revision: str = "0d612dc60e9a"
down_revision: str = "0c180f95890c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Apollo landed as direct-only. Never change existing opt-in choices.
    op.execute("""
        INSERT INTO agent_integration_isolation
            (id, created_at, updated_at, agent_id, provider, source, isolated)
        SELECT gen_random_uuid(), now(), now(), s.agent_id, 'apollo', 'agent_secret', false
        FROM agent_secret s JOIN agent a ON a.id = s.agent_id
        WHERE s.provider = 'apollo' AND a.deleted_at IS NULL
        ON CONFLICT (agent_id, provider, source) DO NOTHING
    """)


def downgrade() -> None:
    # Policy is user intent; deleting it could lose a choice made after the upgrade.
    pass
