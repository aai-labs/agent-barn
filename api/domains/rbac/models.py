from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column, Enum, Field, SQLModel

from api.domains.rbac.catalog import PermissionScope
from api.infrastructure.postgres.models import BaseModel


class Permission(BaseModel, table=True):
    __tablename__: str = "permissions"
    __table_args__ = (sa.Index("uq_permissions_key", "key", unique=True),)

    key: str = Field(nullable=False, max_length=255)


class Role(BaseModel, table=True):
    __tablename__: str = "roles"
    __table_args__ = (
        sa.CheckConstraint(
            "(is_system AND organization_id IS NULL) OR "
            "(NOT is_system AND organization_id IS NOT NULL)",
            name="ck_roles_system_scope",
        ),
        sa.Index(
            "uq_roles_system_name",
            "name",
            unique=True,
            postgresql_where=sa.text("is_system"),
        ),
        sa.Index(
            "uq_roles_organization_name",
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
    scope: PermissionScope = Field(
        sa_column=Column(Enum(PermissionScope), nullable=False)
    )
