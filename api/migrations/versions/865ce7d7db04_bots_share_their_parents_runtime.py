"""bots share their parent's runtime

Revision ID: 865ce7d7db04
Revises: d79ce00137d2
Create Date: 2026-11-11
"""

from alembic import op

revision = "865ce7d7db04"
down_revision = "d79ce00137d2"
branch_labels = None
depends_on = None

SHARED_RUNTIME = """
CREATE OR REPLACE FUNCTION validate_agent_bot_parent()
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
        IF TG_OP = 'UPDATE'
            AND NEW.agent_type IS DISTINCT FROM OLD.agent_type
            AND EXISTS (SELECT 1 FROM agent WHERE parent_agent_id = NEW.id) THEN
            RAISE EXCEPTION 'A Parent Agent and its Bots must use the same runtime'
                USING ERRCODE = 'check_violation';
        END IF;
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

    IF NEW.agent_type <> parent_agent_type THEN
        RAISE EXCEPTION 'A Parent Agent and its Bots must use the same runtime'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

HERMES_ONLY = """
CREATE OR REPLACE FUNCTION validate_agent_bot_parent()
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


def upgrade() -> None:
    op.execute(SHARED_RUNTIME)


def downgrade() -> None:
    op.execute(HERMES_ONLY)
