"""Add Permission catalogue and Agent Access Roles.

Revision ID: a6f2c9d18e47
Revises: d3f9a1c7b2e5
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6f2c9d18e47"
down_revision: Union[str, None] = "d3f9a1c7b2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENT_OWNER_ROLE_ID = UUID("8f2a47ff-7caf-5ded-9027-4a16b85620b3")
AGENT_EDITOR_ROLE_ID = UUID("30e5e846-5e24-548f-a068-2505f774ce35")
AGENT_VIEWER_ROLE_ID = UUID("c7da77aa-bf9c-5626-8bad-5e0ca5159b5d")

AGENT_ACCESS_ROLE_IDS = {
    "OWNER": AGENT_OWNER_ROLE_ID,
    "EDITOR": AGENT_EDITOR_ROLE_ID,
    "VIEWER": AGENT_VIEWER_ROLE_ID,
}

PERMISSION_IDS = {
    "organization.read": UUID("9652eb48-fd1c-5880-b578-4549365e17f3"),
    "organization.update": UUID("2cae72d2-b48b-5919-9fb3-ab50b8319ea5"),
    "organization.delete": UUID("aea08f54-5f04-5093-92ce-42a066b0bbce"),
    "organization.ownership.transfer": UUID("1589db95-014e-5b17-8bc9-90b6187a3900"),
    "membership.read": UUID("1c7bffa3-5b36-5abc-be31-4f7aacd7252e"),
    "membership.invite": UUID("40cade27-b0b2-5657-91ba-95ac1392ff51"),
    "membership.role.update": UUID("6f05fb49-ba9b-5082-be5b-c1e461873d5c"),
    "membership.remove": UUID("20fd8db9-78c5-51bd-9377-a37f75c55649"),
    "agent.create": UUID("601c6540-6a18-5244-b610-10a4763cf4aa"),
    "agent.read": UUID("76bba6c5-b1bc-5fc2-af28-1eb57bb81fec"),
    "agent.update": UUID("86500651-f05b-5c39-bb56-dc7dcd154cd6"),
    "agent.delete": UUID("86b3798f-3409-5f7d-bbc2-2d260cfd96d1"),
    "agent.lifecycle.manage": UUID("61db56c3-339c-51d7-ab33-b6afbaa9fc8a"),
    "agent.access.manage": UUID("8c5ae860-1a12-52e0-8902-de39b94e8145"),
    "agent.secret.manage": UUID("4412d59f-4e8c-5e7e-81a9-b257f99f9dbf"),
    "template.read": UUID("a07c3af3-17d6-53cf-841a-80d509b94de4"),
    "template.manage": UUID("7b44d5da-b324-586b-9d32-d9c49c293037"),
    "skill.read": UUID("36494947-1572-5cdd-8853-79a2bdbf8c4f"),
    "skill.manage": UUID("222ab95b-f67b-5275-8139-3f601574f3e1"),
    "activity.read": UUID("3f24e385-7c5e-56f0-828c-502985376af9"),
    "cost.read": UUID("b6557147-248a-5d34-8bb2-7c51944d9ee7"),
}

VIEWER_PERMISSIONS = {
    "agent.read",
    "activity.read",
    "cost.read",
}
EDITOR_PERMISSIONS = VIEWER_PERMISSIONS | {
    "agent.update",
    "agent.lifecycle.manage",
    "agent.secret.manage",
}
AGENT_OWNER_PERMISSIONS = EDITOR_PERMISSIONS | {
    "agent.delete",
    "agent.access.manage",
}


def _agent_access_role_permission_rows() -> list[dict[str, UUID]]:
    grants = {
        AGENT_OWNER_ROLE_ID: AGENT_OWNER_PERMISSIONS,
        AGENT_EDITOR_ROLE_ID: EDITOR_PERMISSIONS,
        AGENT_VIEWER_ROLE_ID: VIEWER_PERMISSIONS,
    }
    return [
        {"role_id": role_id, "permission_id": PERMISSION_IDS[key]}
        for role_id, permissions in grants.items()
        for key in sorted(permissions)
    ]


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_permissions_key", "permissions", ["key"], unique=True)

    op.create_table(
        "agent_access_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "(is_system AND organization_id IS NULL) OR (NOT is_system AND organization_id IS NOT NULL)",
            name="ck_agent_access_roles_system_scope",
        ),
        sa.CheckConstraint(
            "NOT is_system OR "
            "(id = '8f2a47ff-7caf-5ded-9027-4a16b85620b3'::uuid AND name = 'OWNER') OR "
            "(id = '30e5e846-5e24-548f-a068-2505f774ce35'::uuid AND name = 'EDITOR') OR "
            "(id = 'c7da77aa-bf9c-5626-8bad-5e0ca5159b5d'::uuid AND name = 'VIEWER')",
            name="ck_agent_access_roles_fixed_system_identity",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_agent_access_role_id_organization",
        ),
    )
    op.create_index(
        "uq_agent_access_roles_system_name",
        "agent_access_roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_system"),
    )
    op.create_index(
        "uq_agent_access_roles_organization_name",
        "agent_access_roles",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("NOT is_system"),
    )

    op.create_table(
        "agent_access_role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["agent_access_roles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    timestamp = datetime.now(timezone.utc)
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("key", sa.String(length=255)),
    )
    op.bulk_insert(
        permissions_table,
        [
            {
                "id": permission_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "key": key,
            }
            for key, permission_id in PERMISSION_IDS.items()
        ],
    )

    agent_access_roles_table = sa.table(
        "agent_access_roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String(length=64)),
        sa.column("is_system", sa.Boolean()),
    )
    op.bulk_insert(
        agent_access_roles_table,
        [
            {
                "id": role_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "organization_id": None,
                "name": name,
                "is_system": True,
            }
            for name, role_id in AGENT_ACCESS_ROLE_IDS.items()
        ],
    )

    agent_access_role_permissions_table = sa.table(
        "agent_access_role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
    )
    op.bulk_insert(
        agent_access_role_permissions_table,
        _agent_access_role_permission_rows(),
    )

    op.create_unique_constraint(
        "uq_user_organization_id_organization",
        "user_organization",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_agent_id_organization",
        "agent",
        ["id", "organization_id"],
    )

    # The pre-AF-150 schema stored no creator ID, access assignment, or audit
    # event from which creator provenance could be recovered reliably. Existing
    # rows therefore remain unknown rather than receiving a heuristic Owner.
    op.add_column(
        "agent",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_created_by_user",
        "agent",
        "user",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_created_by_user_id",
        "agent",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "agent_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "organization_id"],
            ["user_organization.id", "user_organization.organization_id"],
            name="fk_agent_access_membership_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_access_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["access_role_id"],
            ["agent_access_roles.id"],
            name="fk_agent_access_role",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "agent_id",
            name="uq_agent_access_membership_agent",
        ),
    )
    op.create_index("ix_agent_access_membership", "agent_access", ["membership_id"])
    op.create_index("ix_agent_access_agent", "agent_access", ["agent_id"])
    op.create_index("ix_agent_access_role", "agent_access", ["access_role_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO agent_access (
                id, created_at, updated_at, organization_id,
                membership_id, agent_id, access_role_id
            )
            SELECT
                gen_random_uuid(), now(), now(),
                membership.organization_id, membership.id, agent.id, :editor_role_id
            FROM user_organization AS membership
            JOIN "user" AS member_user ON member_user.id = membership.user_id
            JOIN agent ON agent.organization_id = membership.organization_id
            WHERE membership.role = 'MEMBER'::organizationrole
              AND member_user.email_verified_at IS NOT NULL
            ON CONFLICT (membership_id, agent_id) DO NOTHING
            """
        ).bindparams(editor_role_id=AGENT_EDITOR_ROLE_ID)
    )
    op.execute(
        """
        CREATE FUNCTION validate_agent_access_role_scope()
        RETURNS trigger AS $$
        DECLARE
            target_organization_id uuid;
            target_is_system boolean;
        BEGIN
            SELECT organization_id, is_system
            INTO target_organization_id, target_is_system
            FROM agent_access_roles
            WHERE id = NEW.access_role_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent Access Role % does not exist', NEW.access_role_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            IF NOT target_is_system
               AND target_organization_id IS DISTINCT FROM NEW.organization_id THEN
                RAISE EXCEPTION 'Agent Access Role % does not belong to Organization %',
                    NEW.access_role_id, NEW.organization_id
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_access_role_scope
        BEFORE INSERT OR UPDATE OF access_role_id, organization_id
        ON agent_access
        FOR EACH ROW EXECUTE FUNCTION validate_agent_access_role_scope();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_agent_access_role_scope_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.is_system THEN
                RAISE EXCEPTION 'System Agent Access Role % cannot be deleted', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF OLD.is_system THEN
                    RAISE EXCEPTION 'System Agent Access Role % cannot be changed', OLD.id
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.is_system IS DISTINCT FROM OLD.is_system THEN
                    RAISE EXCEPTION 'Agent Access Role scope cannot be changed'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_access_role_scope_immutability
        BEFORE UPDATE OR DELETE ON agent_access_roles
        FOR EACH ROW EXECUTE FUNCTION enforce_agent_access_role_scope_immutability();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_permission_catalogue_immutability()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Permission catalogue cannot be changed'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_permission_catalogue_immutability
        BEFORE INSERT OR UPDATE OR DELETE ON permissions
        FOR EACH ROW EXECUTE FUNCTION enforce_permission_catalogue_immutability();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_system_agent_role_grant_immutability()
        RETURNS trigger AS $$
        DECLARE
            old_is_system boolean := false;
            new_is_system boolean := false;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                SELECT is_system INTO old_is_system
                FROM agent_access_roles WHERE id = OLD.role_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                SELECT is_system INTO new_is_system
                FROM agent_access_roles WHERE id = NEW.role_id;
            END IF;
            IF COALESCE(old_is_system, false) OR COALESCE(new_is_system, false) THEN
                RAISE EXCEPTION 'System Agent Access Role grants cannot be changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_system_agent_role_grant_immutability
        BEFORE INSERT OR UPDATE OR DELETE ON agent_access_role_permissions
        FOR EACH ROW EXECUTE FUNCTION enforce_system_agent_role_grant_immutability();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_agent_access_role_scope ON agent_access")
    op.execute("DROP FUNCTION validate_agent_access_role_scope()")
    op.execute("DROP TRIGGER trg_permission_catalogue_immutability ON permissions")
    op.execute("DROP FUNCTION enforce_permission_catalogue_immutability()")
    op.execute(
        "DROP TRIGGER trg_system_agent_role_grant_immutability ON agent_access_role_permissions"
    )
    op.execute("DROP FUNCTION enforce_system_agent_role_grant_immutability()")
    op.execute(
        "DROP TRIGGER trg_agent_access_role_scope_immutability ON agent_access_roles"
    )
    op.execute("DROP FUNCTION enforce_agent_access_role_scope_immutability()")

    op.drop_index("ix_agent_access_role", table_name="agent_access")
    op.drop_index("ix_agent_access_agent", table_name="agent_access")
    op.drop_index("ix_agent_access_membership", table_name="agent_access")
    op.drop_table("agent_access")

    op.drop_index("ix_agent_created_by_user_id", table_name="agent")
    op.drop_constraint("fk_agent_created_by_user", "agent", type_="foreignkey")
    op.drop_column("agent", "created_by_user_id")
    op.drop_constraint("uq_agent_id_organization", "agent", type_="unique")
    op.drop_constraint(
        "uq_user_organization_id_organization",
        "user_organization",
        type_="unique",
    )

    op.drop_table("agent_access_role_permissions")
    op.drop_index(
        "uq_agent_access_roles_organization_name",
        table_name="agent_access_roles",
    )
    op.drop_index(
        "uq_agent_access_roles_system_name",
        table_name="agent_access_roles",
    )
    op.drop_table("agent_access_roles")
    op.drop_index("uq_permissions_key", table_name="permissions")
    op.drop_table("permissions")
