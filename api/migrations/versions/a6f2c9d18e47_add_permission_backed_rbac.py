"""Add permission-backed roles and assigned Agent access.

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

OWNER_ROLE_ID = UUID("5dd0b6b3-2a19-5d6d-9c91-50f9503563a6")
ADMIN_ROLE_ID = UUID("1222b10c-3f24-54ca-bbeb-fce956134f70")
MEMBER_ROLE_ID = UUID("d369b23a-01dd-5aeb-bd53-c463b3c4cd1a")

ROLE_IDS = {
    "OWNER": OWNER_ROLE_ID,
    "ADMIN": ADMIN_ROLE_ID,
    "MEMBER": MEMBER_ROLE_ID,
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
    "agent.start": UUID("61db56c3-339c-51d7-ab33-b6afbaa9fc8a"),
    "agent.stop": UUID("b7355e30-138f-5e19-a8fd-939fe8e34c91"),
    "agent.access.manage": UUID("8c5ae860-1a12-52e0-8902-de39b94e8145"),
    "agent.secret.manage": UUID("4412d59f-4e8c-5e7e-81a9-b257f99f9dbf"),
    "template.read": UUID("a07c3af3-17d6-53cf-841a-80d509b94de4"),
    "template.manage": UUID("7b44d5da-b324-586b-9d32-d9c49c293037"),
    "skill.read": UUID("36494947-1572-5cdd-8853-79a2bdbf8c4f"),
    "skill.manage": UUID("222ab95b-f67b-5275-8139-3f601574f3e1"),
    "activity.read": UUID("3f24e385-7c5e-56f0-828c-502985376af9"),
    "cost.read": UUID("b6557147-248a-5d34-8bb2-7c51944d9ee7"),
    "audit.read": UUID("9143455b-b4d6-58d6-9968-2086e9a24ebf"),
}

OWNER_PERMISSIONS = frozenset(PERMISSION_IDS)
ADMIN_PERMISSIONS = OWNER_PERMISSIONS - {
    "organization.delete",
    "organization.ownership.transfer",
}
MEMBER_ORGANIZATION_PERMISSIONS = {
    "organization.read",
    "agent.create",
    "template.read",
    "skill.read",
}
MEMBER_ASSIGNED_PERMISSIONS = {
    "agent.read",
    "agent.update",
    "agent.delete",
    "agent.start",
    "agent.stop",
    "agent.access.manage",
    "agent.secret.manage",
    "activity.read",
    "cost.read",
}

permission_scope_enum = postgresql.ENUM(
    "ASSIGNED",
    "ORGANIZATION",
    name="permissionscope",
    create_type=False,
)
organization_role_enum = postgresql.ENUM(
    "ADMIN",
    "MEMBER",
    "OWNER",
    name="organizationrole",
    create_type=False,
)


def _role_permission_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(OWNER_PERMISSIONS):
        rows.append(
            {
                "role_id": OWNER_ROLE_ID,
                "permission_id": PERMISSION_IDS[key],
                "scope": "ORGANIZATION",
            }
        )
    for key in sorted(ADMIN_PERMISSIONS):
        rows.append(
            {
                "role_id": ADMIN_ROLE_ID,
                "permission_id": PERMISSION_IDS[key],
                "scope": "ORGANIZATION",
            }
        )
    for key in sorted(MEMBER_ORGANIZATION_PERMISSIONS):
        rows.append(
            {
                "role_id": MEMBER_ROLE_ID,
                "permission_id": PERMISSION_IDS[key],
                "scope": "ORGANIZATION",
            }
        )
    for key in sorted(MEMBER_ASSIGNED_PERMISSIONS):
        rows.append(
            {
                "role_id": MEMBER_ROLE_ID,
                "permission_id": PERMISSION_IDS[key],
                "scope": "ASSIGNED",
            }
        )
    return rows


def upgrade() -> None:
    permission_scope_enum.create(op.get_bind(), checkfirst=True)

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
        "roles",
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
            "(is_system AND organization_id IS NULL) OR "
            "(NOT is_system AND organization_id IS NOT NULL)",
            name="ck_roles_system_scope",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_roles_system_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_system"),
    )
    op.create_index(
        "uq_roles_organization_name",
        "roles",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("NOT is_system"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", permission_scope_enum, nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
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

    roles_table = sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("organization_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String(length=64)),
        sa.column("is_system", sa.Boolean()),
    )
    op.bulk_insert(
        roles_table,
        [
            {
                "id": role_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "organization_id": None,
                "name": role_name,
                "is_system": True,
            }
            for role_name, role_id in ROLE_IDS.items()
        ],
    )

    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
        sa.column("scope", permission_scope_enum),
    )
    op.bulk_insert(role_permissions_table, _role_permission_rows())

    op.add_column(
        "user_organization",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_organization_role",
        "user_organization",
        "roles",
        ["role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            UPDATE user_organization
            SET role_id = CASE role::text
                WHEN 'OWNER' THEN :owner_id
                WHEN 'ADMIN' THEN :admin_id
                WHEN 'MEMBER' THEN :member_id
            END
            """
        ).bindparams(
            owner_id=OWNER_ROLE_ID,
            admin_id=ADMIN_ROLE_ID,
            member_id=MEMBER_ROLE_ID,
        )
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM user_organization WHERE role_id IS NULL) THEN
                RAISE EXCEPTION 'Unable to map every membership to a system role';
            END IF;
        END $$;
        """
    )
    op.alter_column("user_organization", "role_id", nullable=False)

    op.drop_index(
        "uq_user_organization_one_owner_per_org",
        table_name="user_organization",
    )
    op.create_index(
        "uq_user_organization_one_owner_per_org",
        "user_organization",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text(f"role_id = '{OWNER_ROLE_ID}'::uuid"),
    )
    op.drop_column("user_organization", "role")
    organization_role_enum.drop(op.get_bind(), checkfirst=True)

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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "agent_id",
            name="uq_agent_access_membership_agent",
        ),
    )
    op.create_index("ix_agent_access_membership", "agent_access", ["membership_id"])
    op.create_index("ix_agent_access_agent", "agent_access", ["agent_id"])

    op.execute(
        """
        INSERT INTO agent_access (
            id, created_at, updated_at, organization_id, membership_id, agent_id
        )
        SELECT
            gen_random_uuid(), now(), now(),
            membership.organization_id, membership.id, agent.id
        FROM user_organization AS membership
        JOIN agent ON agent.organization_id = membership.organization_id
        ON CONFLICT (membership_id, agent_id) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE FUNCTION validate_user_organization_role_scope()
        RETURNS trigger AS $$
        DECLARE
            target_organization_id uuid;
            target_is_system boolean;
        BEGIN
            SELECT organization_id, is_system
            INTO target_organization_id, target_is_system
            FROM roles
            WHERE id = NEW.role_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Role % does not exist', NEW.role_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            IF NOT target_is_system
               AND target_organization_id IS DISTINCT FROM NEW.organization_id THEN
                RAISE EXCEPTION 'Role % does not belong to organization %',
                    NEW.role_id, NEW.organization_id
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_user_organization_role_scope
        BEFORE INSERT OR UPDATE OF role_id, organization_id
        ON user_organization
        FOR EACH ROW EXECUTE FUNCTION validate_user_organization_role_scope();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_role_scope_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.is_system THEN
                RAISE EXCEPTION 'System Role % cannot be deleted', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF OLD.is_system THEN
                    RAISE EXCEPTION 'System Role % cannot be changed', OLD.id
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.is_system IS DISTINCT FROM OLD.is_system THEN
                    RAISE EXCEPTION 'Role scope cannot be changed'
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
        CREATE TRIGGER trg_roles_scope_immutability
        BEFORE UPDATE OR DELETE ON roles
        FOR EACH ROW EXECUTE FUNCTION enforce_role_scope_immutability();
        """
    )


def downgrade() -> None:
    organization_role_enum.create(op.get_bind(), checkfirst=True)

    op.execute("DROP TRIGGER trg_user_organization_role_scope ON user_organization")
    op.execute("DROP FUNCTION validate_user_organization_role_scope()")
    op.execute("DROP TRIGGER trg_roles_scope_immutability ON roles")
    op.execute("DROP FUNCTION enforce_role_scope_immutability()")

    op.add_column(
        "user_organization",
        sa.Column("role", organization_role_enum, nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE user_organization
            SET role = CASE role_id
                WHEN :owner_id THEN 'OWNER'::organizationrole
                WHEN :admin_id THEN 'ADMIN'::organizationrole
                WHEN :member_id THEN 'MEMBER'::organizationrole
            END
            """
        ).bindparams(
            owner_id=OWNER_ROLE_ID,
            admin_id=ADMIN_ROLE_ID,
            member_id=MEMBER_ROLE_ID,
        )
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM user_organization WHERE role IS NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade memberships using custom roles';
            END IF;
        END $$;
        """
    )
    op.alter_column("user_organization", "role", nullable=False)

    op.drop_index(
        "uq_user_organization_one_owner_per_org",
        table_name="user_organization",
    )
    op.create_index(
        "uq_user_organization_one_owner_per_org",
        "user_organization",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER'"),
    )

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

    op.drop_constraint(
        "fk_user_organization_role",
        "user_organization",
        type_="foreignkey",
    )
    op.drop_column("user_organization", "role_id")

    op.drop_table("role_permissions")
    op.drop_index("uq_roles_organization_name", table_name="roles")
    op.drop_index("uq_roles_system_name", table_name="roles")
    op.drop_table("roles")
    op.drop_index("uq_permissions_key", table_name="permissions")
    op.drop_table("permissions")
    permission_scope_enum.drop(op.get_bind(), checkfirst=True)
