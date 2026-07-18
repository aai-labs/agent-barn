from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, none

from api.domains.auth.exceptions import ForbiddenException
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import (
    ADMIN_ROLE_ID,
    MEMBER_ROLE_ID,
    OWNER_ROLE_ID,
    SYSTEM_ROLE_GRANTS,
    PermissionKey,
    PermissionScope,
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
    repository.get_permission_scope.side_effect = lambda role_id, permission: (
        SYSTEM_ROLE_GRANTS.get(role_id, {}).get(permission)
    )
    return repository


def test_resolve_returns_seeded_owner_admin_and_member_scopes():
    policy = PermissionPolicy(repository=_system_catalogue_repository())

    owner_context, owner_membership = _context(OWNER_ROLE_ID)
    admin_context, admin_membership = _context(ADMIN_ROLE_ID)
    member_context, member_membership = _context(MEMBER_ROLE_ID)

    assert_that(
        policy.resolve(
            owner_context,
            owner_membership.organization_id,
            PermissionKey.ORGANIZATION_DELETE,
        ),
        equal_to(
            AuthorizationScope(
                organization_id=owner_membership.organization_id,
                scope=PermissionScope.ORGANIZATION,
                membership_id=None,
            )
        ),
    )
    assert_that(
        policy.resolve(
            admin_context,
            admin_membership.organization_id,
            PermissionKey.ORGANIZATION_DELETE,
        ),
        none(),
    )
    assert_that(
        policy.resolve(
            member_context,
            member_membership.organization_id,
            PermissionKey.AGENT_CREATE,
        ),
        equal_to(
            AuthorizationScope(
                organization_id=member_membership.organization_id,
                scope=PermissionScope.ORGANIZATION,
                membership_id=None,
            )
        ),
    )
    assert_that(
        policy.resolve(
            member_context,
            member_membership.organization_id,
            PermissionKey.AGENT_READ,
        ),
        equal_to(
            AuthorizationScope(
                organization_id=member_membership.organization_id,
                scope=PermissionScope.ASSIGNED,
                membership_id=member_membership.id,
            )
        ),
    )


def test_resolve_denies_missing_permission_by_default():
    context, membership = _context()
    repository = Mock()
    repository.get_permission_scope.return_value = None
    policy = PermissionPolicy(repository=repository)

    assert_that(
        policy.resolve(
            context, membership.organization_id, PermissionKey.MEMBERSHIP_READ
        ),
        none(),
    )

    try:
        policy.require(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
            detail="Missing membership read",
        )
        raise AssertionError("Expected ForbiddenException")
    except ForbiddenException as exc:
        assert_that(exc.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(exc.detail, equal_to("Missing membership read"))


def test_resolve_superuser_uses_transient_explicit_org_context_without_membership():
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
        equal_to(
            AuthorizationScope(
                organization_id=organization_id,
                scope=PermissionScope.ORGANIZATION,
                membership_id=None,
            )
        ),
    )
    repository.get_permission_scope.assert_not_called()


def test_resolve_rejects_target_outside_active_organization():
    context, _ = _context()
    repository = Mock()
    policy = PermissionPolicy(repository=repository)

    assert_that(
        policy.resolve(context, uuid7(), PermissionKey.ORGANIZATION_READ), none()
    )
    repository.get_permission_scope.assert_not_called()


def test_resolve_requires_active_organization_context_even_for_superuser():
    policy = PermissionPolicy(repository=Mock())
    context = CurrentUserContext(user=_user(is_superuser=True))

    try:
        policy.resolve(context, uuid7(), PermissionKey.ORGANIZATION_READ)
        raise AssertionError("Expected ForbiddenException")
    except ForbiddenException as exc:
        assert_that(exc.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_resolve_observes_membership_role_changes_without_caching():
    context, membership = _context(MEMBER_ROLE_ID)
    policy = PermissionPolicy(repository=_system_catalogue_repository())

    assert_that(
        policy.require(context, membership.organization_id, PermissionKey.AGENT_READ),
        equal_to(
            AuthorizationScope(
                organization_id=membership.organization_id,
                scope=PermissionScope.ASSIGNED,
                membership_id=membership.id,
            )
        ),
    )

    membership.role_id = ADMIN_ROLE_ID

    assert_that(
        policy.require(context, membership.organization_id, PermissionKey.AGENT_READ),
        equal_to(
            AuthorizationScope(
                organization_id=membership.organization_id,
                scope=PermissionScope.ORGANIZATION,
                membership_id=None,
            )
        ),
    )


def test_require_returns_scope_when_permission_exists():
    context, membership = _context()
    repository = Mock()
    repository.get_permission_scope.return_value = PermissionScope.ASSIGNED
    policy = PermissionPolicy(repository=repository)

    result = policy.require(
        context, membership.organization_id, PermissionKey.AGENT_UPDATE
    )

    assert_that(result.scope, equal_to(PermissionScope.ASSIGNED))
    assert_that(result.membership_id, equal_to(membership.id))
    assert_that(result.organization_id, equal_to(membership.organization_id))
