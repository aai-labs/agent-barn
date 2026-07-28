from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.auth.exceptions import ForbiddenException
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey, organization_role_allows


@dataclass(frozen=True)
class AuthorizationScope:
    """Repository visibility for an Organization or explicit Agent assignment."""

    organization_id: UUID
    membership_id: UUID | None = None
    permission: PermissionKey | None = None
    include_general_access: bool = False

    @property
    def has_organization_visibility(self) -> bool:
        return self.membership_id is None


@inject
@singleton
@dataclass
class PermissionPolicy:
    """Resolve fixed Organization Role permissions for the active Organization."""

    def resolve(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        permission: PermissionKey,
    ) -> AuthorizationScope | None:
        membership = context.require_current_user_organization()
        if membership.organization_id != organization_id:
            return None
        if context.user.is_superuser or organization_role_allows(membership.role, permission):
            return AuthorizationScope(organization_id=organization_id)
        return None

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
        return self.require(
            context,
            organization_id,
            permission,
            detail=detail,
        )
