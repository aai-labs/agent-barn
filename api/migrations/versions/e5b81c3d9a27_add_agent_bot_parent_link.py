"""add agent bot parent link

Revision ID: e5b81c3d9a27
Revises: 3680352c132d
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b81c3d9a27"
down_revision = "3680352c132d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("parent_agent_id", sa.Uuid(), nullable=True))
    op.add_column("agent", sa.Column("bot_slot", sa.SmallInteger(), nullable=True))
    op.create_foreign_key(
        "fk_agent_parent_agent",
        "agent",
        "agent",
        ["parent_agent_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_agent_bot_slot_with_parent", "agent", "(parent_agent_id IS NULL) = (bot_slot IS NULL)"
    )
    op.create_check_constraint("ck_agent_bot_slot_range", "agent", "bot_slot IS NULL OR bot_slot BETWEEN 1 AND 5")
    op.create_check_constraint("ck_agent_not_own_parent", "agent", "parent_agent_id IS NULL OR parent_agent_id <> id")
    op.create_index(
        "uq_agent_live_bot_slot",
        "agent",
        ["parent_agent_id", "bot_slot"],
        unique=True,
        postgresql_where=sa.text("parent_agent_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION validate_agent_bot_parent()
        RETURNS trigger AS $$
        DECLARE
            parent_parent_id uuid;
            parent_agent_type text;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.parent_agent_id IS DISTINCT FROM OLD.parent_agent_id THEN
                RAISE EXCEPTION 'An Agent''s parent link cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;

            IF NEW.parent_agent_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT parent_agent_id, agent_type
            INTO parent_parent_id, parent_agent_type
            FROM agent
            WHERE id = NEW.parent_agent_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Parent Agent % does not exist', NEW.parent_agent_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            IF parent_parent_id IS NOT NULL THEN
                RAISE EXCEPTION 'A Bot cannot hold Bots'
                    USING ERRCODE = 'check_violation';
            END IF;

            IF parent_agent_type <> 'hermes' OR NEW.agent_type <> 'hermes' THEN
                RAISE EXCEPTION 'A Parent Agent and its Bots must be Hermes'
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_bot_parent
        BEFORE INSERT OR UPDATE OF parent_agent_id, agent_type
        ON agent
        FOR EACH ROW EXECUTE FUNCTION validate_agent_bot_parent();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agent_bot_parent ON agent")
    op.execute("DROP FUNCTION IF EXISTS validate_agent_bot_parent()")
    op.drop_index("uq_agent_live_bot_slot", table_name="agent")
    op.drop_constraint("ck_agent_not_own_parent", "agent", type_="check")
    op.drop_constraint("ck_agent_bot_slot_range", "agent", type_="check")
    op.drop_constraint("ck_agent_bot_slot_with_parent", "agent", type_="check")
    op.drop_constraint("fk_agent_parent_agent", "agent", type_="foreignkey")
    op.drop_column("agent", "bot_slot")
    op.drop_column("agent", "parent_agent_id")
