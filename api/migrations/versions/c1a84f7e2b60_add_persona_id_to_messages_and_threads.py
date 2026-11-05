"""add persona_id to messages and threads

Revision ID: c1a84f7e2b60
Revises: b7d2e94c1a30
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "c1a84f7e2b60"
down_revision = "b7d2e94c1a30"
branch_labels = None
depends_on = None

OLD_THREAD_CONSTRAINT = "uq_web_chat_thread_connection_channel_thread"
DEFAULT_THREAD_INDEX = "uq_web_chat_thread_default"
PERSONA_THREAD_INDEX = "uq_web_chat_thread_persona"
MESSAGE_FK = "fk_agent_chat_message_persona"
THREAD_FK = "fk_web_chat_thread_persona"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agent_chat_message", sa.Column("persona_id", sa.Uuid(), nullable=True))
    op.execute(
        f"ALTER TABLE agent_chat_message ADD CONSTRAINT {MESSAGE_FK} "
        "FOREIGN KEY (persona_id, agent_id) REFERENCES agent_persona (id, agent_id) DEFERRABLE INITIALLY DEFERRED NOT VALID"
    )

    op.add_column("web_chat_thread", sa.Column("persona_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        THREAD_FK, "web_chat_thread", "agent_persona", ["persona_id"], ["id"], deferrable=True, initially="DEFERRED"
    )
    op.drop_constraint(OLD_THREAD_CONSTRAINT, "web_chat_thread", type_="unique")
    op.create_index(
        DEFAULT_THREAD_INDEX,
        "web_chat_thread",
        ["connection_id", "channel_id", "thread_id"],
        unique=True,
        postgresql_where=sa.text("persona_id IS NULL"),
    )
    op.create_index(
        PERSONA_THREAD_INDEX,
        "web_chat_thread",
        ["connection_id", "channel_id", "persona_id", "thread_id"],
        unique=True,
        postgresql_where=sa.text("persona_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM web_chat_thread WHERE persona_id IS NOT NULL")
    op.drop_index(PERSONA_THREAD_INDEX, table_name="web_chat_thread")
    op.drop_index(DEFAULT_THREAD_INDEX, table_name="web_chat_thread")
    op.create_unique_constraint(OLD_THREAD_CONSTRAINT, "web_chat_thread", ["connection_id", "channel_id", "thread_id"])
    op.drop_constraint(THREAD_FK, "web_chat_thread", type_="foreignkey")
    op.drop_column("web_chat_thread", "persona_id")
    op.drop_constraint(MESSAGE_FK, "agent_chat_message", type_="foreignkey")
    op.drop_column("agent_chat_message", "persona_id")
