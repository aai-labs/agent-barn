from datetime import datetime, timezone
from uuid import UUID, uuid7

from hamcrest import assert_that, calling, equal_to, has_properties, none, raises

from api.domains.auth.exceptions import ForbiddenException
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import (
    OrganizationRole,
    PermissionKey,
    organization_role_allows,
)
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser


def _user(*, is_platform_admin: bool = False) -> User:
    return User(
        email=f"{uuid7()}@example.com",
        hashed_password="hashed",
        email_verified_at=datetime.now(timezone.utc),
        is_platform_admin=is_platform_admin,
    )


def _context(
    role: OrganizationRole = OrganizationRole.MEMBER,
    *,
    organization_id: UUID | None = None,
    is_platform_admin: bool = False,
) -> tuple[CurrentUserContext, OrganizationUser]:
    organization_id = organization_id or uuid7()
    user = _user(is_platform_admin=is_platform_admin)
    membership = OrganizationUser(
        user_id=user.id,
        organization_id=organization_id,
        role=role,
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


def test_organization_role_permission_matrix_is_exact():
    owner_permissions = {
        PermissionKey.ORGANIZATION_READ,
        PermissionKey.ORGANIZATION_UPDATE,
        PermissionKey.ORGANIZATION_DELETE,
        PermissionKey.ORGANIZATION_OWNERSHIP_TRANSFER,
        PermissionKey.MEMBERSHIP_READ,
        PermissionKey.MEMBERSHIP_INVITE,
        PermissionKey.MEMBERSHIP_ROLE_UPDATE,
        PermissionKey.MEMBERSHIP_REMOVE,
        PermissionKey.AGENT_CREATE,
        PermissionKey.TEMPLATE_READ,
        PermissionKey.TEMPLATE_MANAGE,
        PermissionKey.SKILL_READ,
        PermissionKey.SKILL_MANAGE,
        PermissionKey.ACTIVITY_READ,
        PermissionKey.COST_READ,
    }
    expected = {
        OrganizationRole.OWNER: owner_permissions,
        OrganizationRole.ADMIN: owner_permissions
        - {
            PermissionKey.ORGANIZATION_DELETE,
            PermissionKey.ORGANIZATION_OWNERSHIP_TRANSFER,
        },
        OrganizationRole.MEMBER: {
            PermissionKey.ORGANIZATION_READ,
            PermissionKey.AGENT_CREATE,
            PermissionKey.TEMPLATE_READ,
            PermissionKey.SKILL_READ,
        },
    }
    actual = {
        role: {permission for permission in PermissionKey if organization_role_allows(role, permission)}
        for role in OrganizationRole
    }

    assert_that(actual, equal_to(expected))


def test_resolve_uses_fixed_organization_role_permissions():
    policy = PermissionPolicy()
    owner_context, owner = _context(OrganizationRole.OWNER)
    admin_context, admin = _context(OrganizationRole.ADMIN)
    member_context, member = _context(OrganizationRole.MEMBER)

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
    policy = PermissionPolicy()

    assert_that(
        policy.resolve(context, membership.organization_id, PermissionKey.MEMBERSHIP_READ),
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


def test_resolve_platform_admin_uses_real_membership_permissions():
    context, membership = _context(OrganizationRole.MEMBER, is_platform_admin=True)
    policy = PermissionPolicy()

    assert_that(
        policy.resolve(context, membership.organization_id, PermissionKey.ORGANIZATION_DELETE),
        none(),
    )
    assert_that(
        policy.resolve(context, membership.organization_id, PermissionKey.ORGANIZATION_READ),
        equal_to(AuthorizationScope(organization_id=membership.organization_id)),
    )


def test_resolve_rejects_target_outside_active_organization():
    context, _ = _context()
    policy = PermissionPolicy()

    assert_that(policy.resolve(context, uuid7(), PermissionKey.ORGANIZATION_READ), none())


def test_resolve_requires_active_organization_context_even_for_platform_admin():
    policy = PermissionPolicy()
    context = CurrentUserContext(user=_user(is_platform_admin=True))

    assert_that(
        calling(policy.resolve).with_args(context, uuid7(), PermissionKey.ORGANIZATION_READ),
        raises(ForbiddenException, matching=has_properties(status_code=403)),
    )


def test_resolve_observes_membership_role_changes_without_caching():
    context, membership = _context(OrganizationRole.MEMBER)
    policy = PermissionPolicy()

    assert_that(
        policy.resolve(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
        ),
        none(),
    )

    membership.role = OrganizationRole.ADMIN

    assert_that(
        policy.require(
            context,
            membership.organization_id,
            PermissionKey.MEMBERSHIP_READ,
        ),
        equal_to(AuthorizationScope(organization_id=membership.organization_id)),
    )


def test_require_organization_returns_scope_when_permission_exists():
    context, membership = _context(OrganizationRole.OWNER)
    policy = PermissionPolicy()

    result = policy.require_organization(
        context,
        membership.organization_id,
        PermissionKey.TEMPLATE_MANAGE,
    )

    assert_that(result, equal_to(AuthorizationScope(membership.organization_id)))
