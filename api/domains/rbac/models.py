from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from api.infrastructure.postgres.models import BaseModel


class Permission(BaseModel, table=True):
    __tablename__: str = "permissions"
    __table_args__ = (sa.Index("uq_permissions_key", "key", unique=True),)

    key: str = Field(nullable=False, max_length=255)


class Role(BaseModel, table=True):
    """One of the fixed Organization Roles assigned to Memberships."""

    __tablename__: str = "roles"
    __table_args__ = (
        sa.CheckConstraint(
            "(id = '5dd0b6b3-2a19-5d6d-9c91-50f9503563a6'::uuid AND name = 'OWNER') OR "
            "(id = '1222b10c-3f24-54ca-bbeb-fce956134f70'::uuid AND name = 'ADMIN') OR "
            "(id = 'd369b23a-01dd-5aeb-bd53-c463b3c4cd1a'::uuid AND name = 'MEMBER')",
            name="ck_roles_fixed_identity",
        ),
        sa.Index("uq_roles_name", "name", unique=True),
    )

    name: str = Field(nullable=False, max_length=64)


class RolePermission(SQLModel, table=True):
    __tablename__: str = "role_permissions"

    role_id: UUID = Field(
        foreign_key="roles.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
    permission_id: UUID = Field(
        foreign_key="permissions.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )


class AgentAccessRole(BaseModel, table=True):
    __tablename__: str = "agent_access_roles"
    __table_args__ = (
        sa.CheckConstraint(
            "(is_system AND organization_id IS NULL) OR "
            "(NOT is_system AND organization_id IS NOT NULL)",
            name="ck_agent_access_roles_system_scope",
        ),
        sa.CheckConstraint(
            "NOT is_system OR "
            "(id = '8f2a47ff-7caf-5ded-9027-4a16b85620b3'::uuid AND name = 'OWNER') OR "
            "(id = '30e5e846-5e24-548f-a068-2505f774ce35'::uuid AND name = 'EDITOR') OR "
            "(id = 'c7da77aa-bf9c-5626-8bad-5e0ca5159b5d'::uuid AND name = 'VIEWER')",
            name="ck_agent_access_roles_fixed_system_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_agent_access_role_id_organization",
        ),
        sa.Index(
            "uq_agent_access_roles_system_name",
            "name",
            unique=True,
            postgresql_where=sa.text("is_system"),
        ),
        sa.Index(
            "uq_agent_access_roles_organization_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=sa.text("NOT is_system"),
        ),
    )

    organization_id: UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        nullable=True,
        ondelete="CASCADE",
    )
    name: str = Field(nullable=False, max_length=64)
    is_system: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={"server_default": "false"},
    )


class AgentAccessRolePermission(SQLModel, table=True):
    __tablename__: str = "agent_access_role_permissions"

    role_id: UUID = Field(
        foreign_key="agent_access_roles.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
    permission_id: UUID = Field(
        foreign_key="permissions.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
