from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlmodel import Session

from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import RolePermission
from api.domains.rbac.repository import RbacRepository


def _removed_grant(repository: RbacRepository, role_id: UUID, permission_id: UUID):
    @contextmanager
    def changed_grant() -> Iterator[None]:
        with Session(repository.delegate.engine) as session:
            grant = session.get(RolePermission, (role_id, permission_id))
            if grant is None:
                raise AssertionError("Missing seeded Organization Role grant")
            session.delete(grant)
            session.commit()
        try:
            yield
        finally:
            with Session(repository.delegate.engine) as session:
                session.add(
                    RolePermission(
                        role_id=role_id,
                        permission_id=permission_id,
                    )
                )
                session.commit()

    return changed_grant()


def role_lacks_permission(
    role_id: UUID, permission: PermissionKey
) -> Callable[[object], object]:
    """Temporarily remove one persisted Organization Role grant."""

    def step(context) -> object:
        repository: RbacRepository = context.injector.get(RbacRepository)
        permission_id = PERMISSION_ID_BY_KEY[permission]
        return _removed_grant(repository, role_id, permission_id)

    return step
