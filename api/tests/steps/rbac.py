from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlmodel import Session

from api.domains.rbac.catalog import (
    PERMISSION_ID_BY_KEY,
    PermissionKey,
    PermissionScope,
)
from api.domains.rbac.models import RolePermission
from api.domains.rbac.repository import RbacRepository


def role_lacks_permission(
    role_id: UUID, permission: PermissionKey
) -> Callable[[object], object]:
    """Temporarily remove one persisted grant after startup seeding."""

    def step(context) -> object:
        repository: RbacRepository = context.injector.get(RbacRepository)
        permission_id = PERMISSION_ID_BY_KEY[permission]

        @contextmanager
        def changed_grant() -> Iterator[None]:
            original_scope: PermissionScope | None = None
            with Session(repository.delegate.engine) as session:
                grant = session.get(RolePermission, (role_id, permission_id))
                if grant is None:
                    raise AssertionError(f"Missing seeded grant for {permission.value}")
                original_scope = grant.scope
                session.delete(grant)
                session.commit()
            try:
                yield
            finally:
                if original_scope is not None:
                    with Session(repository.delegate.engine) as session:
                        session.add(
                            RolePermission(
                                role_id=role_id,
                                permission_id=permission_id,
                                scope=original_scope,
                            )
                        )
                        session.commit()

        return changed_grant()

    return step


def role_permission_has_scope(
    role_id: UUID,
    permission: PermissionKey,
    scope: PermissionScope,
) -> Callable[[object], object]:
    """Temporarily change one persisted grant scope after startup seeding."""

    def step(context) -> object:
        repository: RbacRepository = context.injector.get(RbacRepository)
        permission_id = PERMISSION_ID_BY_KEY[permission]

        @contextmanager
        def changed_scope() -> Iterator[None]:
            with Session(repository.delegate.engine) as session:
                grant = session.get(RolePermission, (role_id, permission_id))
                if grant is None:
                    raise AssertionError(f"Missing seeded grant for {permission.value}")
                original_scope = grant.scope
                grant.scope = scope
                session.add(grant)
                session.commit()
            try:
                yield
            finally:
                with Session(repository.delegate.engine) as session:
                    grant = session.get(RolePermission, (role_id, permission_id))
                    if grant is None:
                        raise AssertionError(
                            f"Missing grant while restoring {permission.value}"
                        )
                    grant.scope = original_scope
                    session.add(grant)
                    session.commit()

        return changed_scope()

    return step
