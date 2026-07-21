from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID, uuid7

from hamcrest import assert_that, calling, equal_to, has_properties, none, raises

from api.domains.auth.exceptions import ForbiddenException
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import (
    ADMIN_ROLE_ID,
    MEMBER_ROLE_ID,
    OWNER_ROLE_ID,
    SYSTEM_ROLE_GRANTS,
    PermissionKey,
)
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser


def _user(*, is_superuser: bool = False) -> User:
    return User(
        email=f"{uuid7()}@example.com",
        hashed_password="hashed",
        email_verified_at=datetime.now(timezone.utc),
        is_superuser=is_superuser,
    )


def _context(
    role_id: UUID = MEMBER_ROLE_ID,
    *,
    organization_id: UUID | None = None,
    is_superuser: bool = False,
) -> tuple[CurrentUserContext, OrganizationUser]:
    organization_id = organization_id or uuid7()
    user = _user(is_superuser=is_superuser)
    membership = OrganizationUser(
        user_id=user.id,
        organization_id=organization_id,
        role_id=role_id,
    )
    return (
        CurrentUserContext(
            user=user,
            organization_ids=[organization_id],
            user_organization_map={organization_id: membership},
            current_user_organization=membership,
        ),
        membership,
    )


def _system_catalogue_repository() -> Mock:
    repository = Mock()
    repository.has_permission.side_effect = lambda role_id, permission: (
        permission in SYSTEM_ROLE_GRANTS.get(role_id, set())
    )
    repository.get_permissions.side_effect = lambda role_id, permissions: {
        permission
        for permission in permissions
        if permission in SYSTEM_ROLE_GRANTS.get(role_id, set())
    }
    return repository


def test_resolve_uses_fixed_organization_role_permissions():
    policy = PermissionPolicy(repository=_system_catalogue_repository())
    owner_context, owner = _context(OWNER_ROLE_ID)
    admin_context, admin = _context(ADMIN_ROLE_ID)
    member_context, member = _context(MEMBER_ROLE_ID)

    assert_that(
        policy.resolve(
            owner_context,
            owner.organization_id,
            PermissionKey.ORGANIZATION_DELETE,
        ),
        equal_to(AuthorizationScope(organization_id=owner.organization_id)),
    )
    assert_that(
        policy.resolve(
            admin_context,
            admin.organization_id,
            PermissionKey.ORGANIZATION_DELETE,
        ),
        none(),
    )
    assert_that(
        policy.resolve(
            member_context,
            member.organization_id,
            PermissionKey.AGENT_CREATE,
        ),
        equal_to(AuthorizationScope(organization_id=member.organization_id)),
    )
    assert_that(
        policy.resolve(
            member_context,
            member.organization_id,
            PermissionKey.AGENT_READ,
        ),
        none(),
    )


def test_resolve_denies_missing_permission_by_default():
    context, membership = _context()
    repository = Mock()
    repository.has_permission.return_value = False
    policy = PermissionPolicy(repository=repository)

    assert_that(
        policy.resolve(
            context, membership.organization_id, PermissionKey.MEMBERSHIP_READ
        ),
        none(),
    )
    assert_that(
        calling(policy.require).with_args(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
            detail="Missing membership read",
        ),
        raises(
            ForbiddenException,
            matching=has_properties(
                status_code=403,
                detail="Missing membership read",
            ),
        ),
    )


def test_resolve_superuser_uses_transient_explicit_org_context():
    organization_id = uuid7()
    user = _user(is_superuser=True)
    transient_membership = OrganizationUser(
        user_id=user.id,
        organization_id=organization_id,
        role_id=OWNER_ROLE_ID,
    )
    context = CurrentUserContext(
        user=user,
        organization_ids=[],
        user_organization_map={},
        current_user_organization=transient_membership,
    )
    repository = Mock()
    policy = PermissionPolicy(repository=repository)

    assert_that(
        policy.resolve(context, organization_id, PermissionKey.ORGANIZATION_DELETE),
        equal_to(AuthorizationScope(organization_id=organization_id)),
    )
    repository.has_permission.assert_not_called()


def test_resolve_rejects_target_outside_active_organization():
    context, _ = _context()
    repository = Mock()
    policy = PermissionPolicy(repository=repository)

    assert_that(
        policy.resolve(context, uuid7(), PermissionKey.ORGANIZATION_READ), none()
    )
    repository.has_permission.assert_not_called()


def test_resolve_requires_active_organization_context_even_for_superuser():
    policy = PermissionPolicy(repository=Mock())
    context = CurrentUserContext(user=_user(is_superuser=True))

    assert_that(
        calling(policy.resolve).with_args(
            context, uuid7(), PermissionKey.ORGANIZATION_READ
        ),
        raises(ForbiddenException, matching=has_properties(status_code=403)),
    )


def test_resolve_observes_membership_role_changes_without_caching():
    context, membership = _context(MEMBER_ROLE_ID)
    policy = PermissionPolicy(repository=_system_catalogue_repository())

    assert_that(
        policy.resolve(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
        ),
        none(),
    )

    membership.role_id = ADMIN_ROLE_ID

    assert_that(
        policy.require(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
        ),
        equal_to(AuthorizationScope(organization_id=membership.organization_id)),
    )


def test_require_organization_returns_scope_when_permission_exists():
    context, membership = _context()
    repository = Mock()
    repository.has_permission.return_value = True
    policy = PermissionPolicy(repository=repository)

    result = policy.require_organization(
        context,
        membership.organization_id,
        PermissionKey.TEMPLATE_MANAGE,
    )

    assert_that(result, equal_to(AuthorizationScope(membership.organization_id)))
