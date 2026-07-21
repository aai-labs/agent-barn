from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.repository import RbacRepository


def _without_permission(
    repository: RbacRepository,
    role_id: UUID,
    permission: PermissionKey,
):
    original = repository.get_permissions

    def filtered_permissions(
        requested_role_id: UUID,
        permissions: Iterable[PermissionKey],
    ) -> set[PermissionKey]:
        result = original(requested_role_id, permissions)
        if requested_role_id == role_id:
            result.discard(permission)
        return result

    @contextmanager
    def changed_grant() -> Iterator[None]:
        with patch.object(
            repository,
            "get_permissions",
            side_effect=filtered_permissions,
        ):
            yield

    return changed_grant()


def role_lacks_permission(
    role_id: UUID, permission: PermissionKey
) -> Callable[[object], object]:
    """Temporarily simulate a denied repository lookup without mutating locked grants."""

    def step(context) -> object:
        repository: RbacRepository = context.injector.get(RbacRepository)
        return _without_permission(repository, role_id, permission)

    return step
