from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, or_, select

from api.domains.rbac.catalog import (
    PERMISSION_ID_BY_KEY,
    PERMISSIONS,
    SYSTEM_AGENT_ACCESS_ROLE_GRANTS,
    SYSTEM_AGENT_ACCESS_ROLES,
    SYSTEM_ROLE_GRANTS,
    SYSTEM_ROLES,
    PermissionKey,
)
from api.domains.rbac.models import (
    AgentAccessRole,
    AgentAccessRolePermission,
    Permission,
    Role,
    RolePermission,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class RbacSeedConflictError(RuntimeError):
    pass


@inject
@singleton
@dataclass
class RbacRepository:
    delegate: PostgresRepositoryDelegate

    def has_permission(self, role_id: UUID, permission: PermissionKey) -> bool:
        return permission in self.get_permissions(role_id, (permission,))

    def get_permissions(
        self, role_id: UUID, permissions: Iterable[PermissionKey]
    ) -> set[PermissionKey]:
        requested = tuple(dict.fromkeys(permissions))
        if not requested:
            return set()
        by_value = {permission.value: permission for permission in requested}
        with Session(self.delegate.engine) as session:
            keys = session.exec(
                select(Permission.key)
                .join(
                    RolePermission,
                    col(Permission.id) == col(RolePermission.permission_id),
                )
                .where(
                    col(RolePermission.role_id) == role_id,
                    col(Permission.key).in_(list(by_value)),
                )
            ).all()
        return {by_value[key] for key in keys}

    def get_agent_access_role_permissions(
        self, role_id: UUID, permissions: Iterable[PermissionKey] | None = None
    ) -> set[PermissionKey]:
        requested = tuple(dict.fromkeys(permissions or tuple(PermissionKey)))
        if not requested:
            return set()
        by_value = {permission.value: permission for permission in requested}
        with Session(self.delegate.engine) as session:
            keys = session.exec(
                select(Permission.key)
                .join(
                    AgentAccessRolePermission,
                    col(Permission.id) == col(AgentAccessRolePermission.permission_id),
                )
                .where(
                    col(AgentAccessRolePermission.role_id) == role_id,
                    col(Permission.key).in_(list(by_value)),
                )
            ).all()
        return {by_value[key] for key in keys}

    def list_agent_access_roles(
        self, organization_id: UUID
    ) -> list[tuple[AgentAccessRole, set[PermissionKey]]]:
        """Return locked defaults and roles owned by the active Organization."""
        with Session(self.delegate.engine) as session:
            roles = list(
                session.exec(
                    select(AgentAccessRole)
                    .where(
                        or_(
                            col(AgentAccessRole.is_system).is_(True),
                            col(AgentAccessRole.organization_id) == organization_id,
                        )
                    )
                    .order_by(
                        col(AgentAccessRole.is_system).desc(),
                        col(AgentAccessRole.name).asc(),
                    )
                ).all()
            )
            role_ids = [role.id for role in roles]
            grants = (
                session.exec(
                    select(AgentAccessRolePermission.role_id, Permission.key)
                    .join(
                        Permission,
                        col(Permission.id)
                        == col(AgentAccessRolePermission.permission_id),
                    )
                    .where(col(AgentAccessRolePermission.role_id).in_(role_ids))
                ).all()
                if role_ids
                else []
            )
        permissions_by_role: dict[UUID, set[PermissionKey]] = {
            role_id: set() for role_id in role_ids
        }
        for role_id, key in grants:
            permissions_by_role[role_id].add(PermissionKey(key))
        return [(role, permissions_by_role[role.id]) for role in roles]

    def get_agent_access_role(
        self, role_id: UUID, organization_id: UUID
    ) -> AgentAccessRole | None:
        """Resolve a system role or a custom role owned by one Organization."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentAccessRole).where(
                    col(AgentAccessRole.id) == role_id,
                    or_(
                        col(AgentAccessRole.is_system).is_(True),
                        col(AgentAccessRole.organization_id) == organization_id,
                    ),
                )
            ).first()

    def ensure_system_catalogue(self) -> None:
        with Session(self.delegate.engine) as session:
            self._seed_permissions(session)
            self._seed_roles(session)
            self._seed_agent_access_roles(session)
            self._seed_role_permissions(session)
            self._seed_agent_access_role_permissions(session)
            self._validate_exact_system_catalogue(session)
            session.commit()

    @staticmethod
    def _seed_permissions(session: Session) -> None:
        for seed in PERMISSIONS:
            by_id = session.get(Permission, seed.id)
            by_key = session.exec(
                select(Permission).where(col(Permission.key) == seed.key.value)
            ).first()
            if by_id is not None and by_id.key != seed.key.value:
                raise RbacSeedConflictError(
                    f"Permission ID {seed.id} has unexpected key {by_id.key}"
                )
            if by_key is not None and by_key.id != seed.id:
                raise RbacSeedConflictError(
                    f"Permission key {seed.key.value} has unexpected ID {by_key.id}"
                )
            if by_id is None:
                session.add(Permission(id=seed.id, key=seed.key.value))
        session.flush()

    @staticmethod
    def _seed_roles(session: Session) -> None:
        for seed in SYSTEM_ROLES:
            by_id = session.get(Role, seed.id)
            by_name = session.exec(
                select(Role).where(col(Role.name) == seed.name)
            ).first()
            if by_id is not None and by_id.name != seed.name:
                raise RbacSeedConflictError(
                    f"Organization Role ID {seed.id} has unexpected attributes"
                )
            if by_name is not None and by_name.id != seed.id:
                raise RbacSeedConflictError(
                    f"Organization Role {seed.name} has unexpected ID {by_name.id}"
                )
            if by_id is None:
                session.add(Role(id=seed.id, name=seed.name))
        session.flush()

    @staticmethod
    def _seed_agent_access_roles(session: Session) -> None:
        for seed in SYSTEM_AGENT_ACCESS_ROLES:
            by_id = session.get(AgentAccessRole, seed.id)
            by_name = session.exec(
                select(AgentAccessRole).where(
                    col(AgentAccessRole.name) == seed.name,
                    col(AgentAccessRole.is_system).is_(True),
                )
            ).first()
            if by_id is not None and (
                by_id.name != seed.name
                or not by_id.is_system
                or by_id.organization_id is not None
            ):
                raise RbacSeedConflictError(
                    f"System Agent Access Role ID {seed.id} has unexpected attributes"
                )
            if by_name is not None and by_name.id != seed.id:
                raise RbacSeedConflictError(
                    f"System Agent Access Role {seed.name} has unexpected ID "
                    f"{by_name.id}"
                )
            if by_id is None:
                session.add(
                    AgentAccessRole(
                        id=seed.id,
                        name=seed.name,
                        is_system=True,
                        organization_id=None,
                    )
                )
        session.flush()

    @staticmethod
    def _seed_role_permissions(session: Session) -> None:
        for role_id, grants in SYSTEM_ROLE_GRANTS.items():
            for permission_key in grants:
                permission_id = PERMISSION_ID_BY_KEY[permission_key]
                if session.get(RolePermission, (role_id, permission_id)) is None:
                    session.add(
                        RolePermission(
                            role_id=role_id,
                            permission_id=permission_id,
                        )
                    )
        session.flush()

    @staticmethod
    def _seed_agent_access_role_permissions(session: Session) -> None:
        for role_id, permissions in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.items():
            for permission_key in permissions:
                permission_id = PERMISSION_ID_BY_KEY[permission_key]
                if (
                    session.get(
                        AgentAccessRolePermission,
                        (role_id, permission_id),
                    )
                    is None
                ):
                    session.add(
                        AgentAccessRolePermission(
                            role_id=role_id,
                            permission_id=permission_id,
                        )
                    )
        session.flush()

    @staticmethod
    def _validate_exact_system_catalogue(session: Session) -> None:
        expected_permissions = {
            (permission.id, permission.key.value) for permission in PERMISSIONS
        }
        actual_permissions = {
            (permission.id, permission.key)
            for permission in session.exec(select(Permission)).all()
        }
        if actual_permissions != expected_permissions:
            raise RbacSeedConflictError(
                "Permission catalogue contains unexpected or missing rows"
            )

        expected_roles = {(role.id, role.name) for role in SYSTEM_ROLES}
        actual_roles = {
            (role.id, role.name) for role in session.exec(select(Role)).all()
        }
        if actual_roles != expected_roles:
            raise RbacSeedConflictError(
                "Organization Role catalogue contains unexpected or missing rows"
            )

        expected_agent_roles = {
            (role.id, role.name) for role in SYSTEM_AGENT_ACCESS_ROLES
        }
        actual_agent_roles = {
            (role.id, role.name)
            for role in session.exec(
                select(AgentAccessRole).where(col(AgentAccessRole.is_system).is_(True))
            ).all()
        }
        if actual_agent_roles != expected_agent_roles:
            raise RbacSeedConflictError(
                "System Agent Access Role catalogue contains unexpected or missing rows"
            )

        expected_role_grants = {
            (role_id, PERMISSION_ID_BY_KEY[permission_key])
            for role_id, grants in SYSTEM_ROLE_GRANTS.items()
            for permission_key in grants
        }
        actual_role_grants = {
            (grant.role_id, grant.permission_id)
            for grant in session.exec(select(RolePermission)).all()
        }
        if actual_role_grants != expected_role_grants:
            raise RbacSeedConflictError(
                "Organization Role grants contain unexpected or missing rows"
            )

        expected_agent_grants = {
            (role_id, PERMISSION_ID_BY_KEY[permission_key])
            for role_id, grants in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.items()
            for permission_key in grants
        }
        system_agent_role_ids = [role.id for role in SYSTEM_AGENT_ACCESS_ROLES]
        actual_agent_grants = {
            (grant.role_id, grant.permission_id)
            for grant in session.exec(
                select(AgentAccessRolePermission).where(
                    col(AgentAccessRolePermission.role_id).in_(system_agent_role_ids)
                )
            ).all()
        }
        if actual_agent_grants != expected_agent_grants:
            raise RbacSeedConflictError(
                "System Agent Access Role grants contain unexpected or missing rows"
            )
