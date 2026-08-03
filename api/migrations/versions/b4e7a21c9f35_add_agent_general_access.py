"""Add Agent General Access role to Agent.

Revision ID: b4e7a21c9f35
Revises: a6f2c9d18e47
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e7a21c9f35"
down_revision: str | None = "a6f2c9d18e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column(
            "general_access_role_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_general_access_role",
        "agent",
        "agent_access_roles",
        ["general_access_role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_agent_general_access_role", "agent", ["general_access_role_id"])
    op.execute(
        """
        CREATE FUNCTION validate_agent_general_access_role_scope()
        RETURNS trigger AS $$
        DECLARE
            target_organization_id uuid;
            target_is_system boolean;
        BEGIN
            IF NEW.general_access_role_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT organization_id, is_system
            INTO target_organization_id, target_is_system
            FROM agent_access_roles
            WHERE id = NEW.general_access_role_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent Access Role % does not exist',
                    NEW.general_access_role_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            IF NOT target_is_system
               AND target_organization_id IS DISTINCT FROM NEW.organization_id THEN
                RAISE EXCEPTION 'Agent Access Role % does not belong to Organization %',
                    NEW.general_access_role_id, NEW.organization_id
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_general_access_role_scope
        BEFORE INSERT OR UPDATE OF general_access_role_id, organization_id
        ON agent
        FOR EACH ROW EXECUTE FUNCTION validate_agent_general_access_role_scope();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agent_general_access_role_scope ON agent")
    op.execute("DROP FUNCTION IF EXISTS validate_agent_general_access_role_scope()")
    op.drop_index("ix_agent_general_access_role", table_name="agent")
    op.drop_constraint("fk_agent_general_access_role", "agent", type_="foreignkey")
    op.drop_column("agent", "general_access_role_id")
