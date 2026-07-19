from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.rbac.catalog import (
    PERMISSION_ID_BY_KEY,
    PERMISSIONS,
    SYSTEM_ROLE_GRANTS,
    SYSTEM_ROLES,
    PermissionKey,
    PermissionScope,
)
from api.domains.rbac.models import Permission, Role, RolePermission
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class RbacSeedConflictError(RuntimeError):
    pass


@inject
@singleton
@dataclass
class RbacRepository:
    delegate: PostgresRepositoryDelegate

    def get_permission_scope(
        self, role_id: UUID, permission: PermissionKey
    ) -> PermissionScope | None:
        return self.get_permission_scopes(role_id, (permission,)).get(permission)

    def get_permission_scopes(
        self, role_id: UUID, permissions: Iterable[PermissionKey]
    ) -> dict[PermissionKey, PermissionScope]:
        requested = tuple(dict.fromkeys(permissions))
        if not requested:
            return {}
        by_value = {permission.value: permission for permission in requested}
        with Session(self.delegate.engine) as session:
            query = (
                select(Permission.key, RolePermission.scope)
                .join(
                    RolePermission,
                    col(Permission.id) == col(RolePermission.permission_id),
                )
                .where(
                    col(RolePermission.role_id) == role_id,
                    col(Permission.key).in_(list(by_value)),
                )
            )
            return {
                by_value[key]: cast(PermissionScope, scope)
                for key, scope in session.exec(query).all()
            }

    def ensure_system_catalogue(self) -> None:
        with Session(self.delegate.engine) as session:
            self._seed_permissions(session)
            self._seed_roles(session)
            self._seed_role_permissions(session)
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
                select(Role).where(
                    col(Role.name) == seed.name,
                    col(Role.is_system).is_(True),
                )
            ).first()
            if by_id is not None and (
                by_id.name != seed.name
                or not by_id.is_system
                or by_id.organization_id is not None
            ):
                raise RbacSeedConflictError(
                    f"System role ID {seed.id} has unexpected attributes"
                )
            if by_name is not None and by_name.id != seed.id:
                raise RbacSeedConflictError(
                    f"System role {seed.name} has unexpected ID {by_name.id}"
                )
            if by_id is None:
                session.add(
                    Role(
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
            for permission_key, scope in grants.items():
                permission_id = PERMISSION_ID_BY_KEY[permission_key]
                existing = session.get(
                    RolePermission,
                    (role_id, permission_id),
                )
                if existing is None:
                    session.add(
                        RolePermission(
                            role_id=role_id,
                            permission_id=permission_id,
                            scope=scope,
                        )
                    )
                elif existing.scope != scope:
                    raise RbacSeedConflictError(
                        f"Role {role_id} permission {permission_key.value} "
                        f"has unexpected scope {existing.scope}"
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
            (role.id, role.name)
            for role in session.exec(
                select(Role).where(col(Role.is_system).is_(True))
            ).all()
        }
        if actual_roles != expected_roles:
            raise RbacSeedConflictError(
                "System Role catalogue contains unexpected or missing rows"
            )

        expected_grants = {
            (role_id, PERMISSION_ID_BY_KEY[permission_key], scope)
            for role_id, grants in SYSTEM_ROLE_GRANTS.items()
            for permission_key, scope in grants.items()
        }
        system_role_ids = [role.id for role in SYSTEM_ROLES]
        actual_grants = {
            (grant.role_id, grant.permission_id, grant.scope)
            for grant in session.exec(
                select(RolePermission).where(
                    col(RolePermission.role_id).in_(system_role_ids)
                )
            ).all()
        }
        if actual_grants != expected_grants:
            raise RbacSeedConflictError(
                "System Role grants contain unexpected or missing rows"
            )
