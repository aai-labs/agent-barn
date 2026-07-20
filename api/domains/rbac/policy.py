from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.auth.exceptions import ForbiddenException
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey, PermissionScope
from api.domains.rbac.repository import RbacRepository


@dataclass(frozen=True)
class AuthorizationScope:
    """The resource boundary a caller may use for one permission."""

    organization_id: UUID
    scope: PermissionScope
    membership_id: UUID | None


@inject
@singleton
@dataclass
class PermissionPolicy:
    """Resolve current database-backed permission grants for an active organization."""

    repository: RbacRepository

    def resolve(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        permission: PermissionKey,
    ) -> AuthorizationScope | None:
        membership = context.require_current_user_organization()
        if membership.organization_id != organization_id:
            return None
        if context.user.is_superuser:
            return AuthorizationScope(
                organization_id=organization_id,
                scope=PermissionScope.ORGANIZATION,
                membership_id=None,
            )
        scope = self.repository.get_permission_scope(membership.role_id, permission)
        if scope is None:
            return None
        return AuthorizationScope(
            organization_id=organization_id,
            scope=scope,
            membership_id=(
                membership.id if scope == PermissionScope.ASSIGNED else None
            ),
        )

    def resolve_many(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        permissions: Iterable[PermissionKey],
    ) -> dict[PermissionKey, AuthorizationScope]:
        requested = tuple(dict.fromkeys(permissions))
        if not requested:
            return {}

        # Explicit Organization context is represented by the active Membership. Auth
        # supplies a transient, unpersisted Membership for superusers targeting an org.
        membership = context.require_current_user_organization()
        if membership.organization_id != organization_id:
            return {}

        if context.user.is_superuser:
            return {
                permission: AuthorizationScope(
                    organization_id=organization_id,
                    scope=PermissionScope.ORGANIZATION,
                    membership_id=None,
                )
                for permission in requested
            }

        grants = self.repository.get_permission_scopes(membership.role_id, requested)
        return {
            permission: AuthorizationScope(
                organization_id=organization_id,
                scope=scope,
                membership_id=(
                    membership.id if scope == PermissionScope.ASSIGNED else None
                ),
            )
            for permission, scope in grants.items()
        }

    def require(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission for this organization.",
    ) -> AuthorizationScope:
        authorization_scope = self.resolve(context, organization_id, permission)
        if authorization_scope is None:
            raise ForbiddenException(detail=detail)
        return authorization_scope

    def require_organization(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission for this organization.",
    ) -> AuthorizationScope:
        authorization_scope = self.require(
            context,
            organization_id,
            permission,
            detail=detail,
        )
        if authorization_scope.scope != PermissionScope.ORGANIZATION:
            raise ForbiddenException(detail=detail)
        return authorization_scope
