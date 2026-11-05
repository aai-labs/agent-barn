"""validate the persona message key and index it

Revision ID: d9e36b05a7c2
Revises: c1a84f7e2b60
Create Date: 2026-11-05
"""

from alembic import op

revision = "d9e36b05a7c2"
down_revision = "c1a84f7e2b60"
branch_labels = None
depends_on = None

MESSAGE_FK = "fk_agent_chat_message_persona"
MESSAGE_INDEX = "ix_agent_chat_message_persona"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE agent_chat_message VALIDATE CONSTRAINT {MESSAGE_FK}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {MESSAGE_INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY {MESSAGE_INDEX} "
            "ON agent_chat_message (persona_id, agent_id) WHERE persona_id IS NOT NULL"
        )


def downgrade() -> None:
    op.drop_index(MESSAGE_INDEX, table_name="agent_chat_message")
