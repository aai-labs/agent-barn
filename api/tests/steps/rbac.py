from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

from api.domains.rbac.catalog import (
    OrganizationRole,
    PermissionKey,
    organization_role_allows,
)


def _without_permission(role: OrganizationRole, permission: PermissionKey):
    def filtered_permissions(
        requested_role: OrganizationRole,
        requested_permission: PermissionKey,
    ) -> bool:
        if requested_role == role and requested_permission == permission:
            return False
        return organization_role_allows(requested_role, requested_permission)

    @contextmanager
    def changed_grant() -> Iterator[None]:
        with patch(
            "api.domains.rbac.policy.organization_role_allows",
            side_effect=filtered_permissions,
        ):
            yield

    return changed_grant()


def role_lacks_permission(role: OrganizationRole, permission: PermissionKey) -> Callable[[object], object]:
    """Temporarily simulate a denied policy decision for a fixed Organization Role."""

    def step(context) -> object:
        return _without_permission(role, permission)

    return step
