from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import MEMBER_ROLE_ID, PermissionKey, PermissionScope
from api.domains.rbac.policy import AuthorizationScope
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser


def _context():
    organization_id = uuid7()
    user = User(
        email=f"{uuid7()}@example.com",
        hashed_password="hashed",
        email_verified_at=datetime.now(timezone.utc),
    )
    membership = OrganizationUser(
        user_id=user.id,
        organization_id=organization_id,
        role_id=MEMBER_ROLE_ID,
    )
    context = CurrentUserContext(
        user=user,
        organization_ids=[organization_id],
        user_organization_map={organization_id: membership},
        current_user_organization=membership,
    )
    return context, membership


def _agent(organization_id, *, creator_id=None, status=AgentStatus.STOPPED):
    return Agent(
        organization_id=organization_id,
        created_by_user_id=creator_id,
        name="Agent",
        template_slug="template",
        template_version=1,
        status=status,
    )


def _assigned_scope(organization_id, membership_id):
    return AuthorizationScope(
        organization_id=organization_id,
        scope=PermissionScope.ASSIGNED,
        membership_id=membership_id,
    )


def test_recipient_effective_actions_use_permission_keys_and_cannot_manage_access():
    context, membership = _context()
    agent = _agent(membership.organization_id, creator_id=uuid7())
    scope = _assigned_scope(membership.organization_id, membership.id)
    policy = Mock()
    policy.resolve_many.return_value = {
        permission: scope
        for permission in (
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_START,
            PermissionKey.AGENT_STOP,
            PermissionKey.AGENT_ACCESS_MANAGE,
        )
    }
    repository = Mock()
    repository.find_assigned_agent_ids.return_value = {agent.id}
    authorization = AgentAuthorization(policy=policy, repository=repository)

    actions = authorization.allowed_actions(context, [agent])[agent.id]

    assert_that(
        actions,
        equal_to(
            [
                PermissionKey.AGENT_READ,
                PermissionKey.AGENT_UPDATE,
                PermissionKey.AGENT_START,
            ]
        ),
    )


def test_creator_can_manage_access_and_running_state_filters_actions():
    context, membership = _context()
    agent = _agent(
        membership.organization_id,
        creator_id=context.user.id,
        status=AgentStatus.RUNNING,
    )
    scope = _assigned_scope(membership.organization_id, membership.id)
    policy = Mock()
    policy.resolve_many.return_value = {
        permission: scope
        for permission in (
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_START,
            PermissionKey.AGENT_STOP,
            PermissionKey.AGENT_ACCESS_MANAGE,
            PermissionKey.AGENT_SECRET_MANAGE,
        )
    }
    repository = Mock()
    repository.find_assigned_agent_ids.return_value = {agent.id}
    authorization = AgentAuthorization(policy=policy, repository=repository)

    actions = authorization.allowed_actions(context, [agent])[agent.id]

    assert_that(
        actions,
        equal_to(
            [
                PermissionKey.AGENT_READ,
                PermissionKey.AGENT_STOP,
                PermissionKey.AGENT_ACCESS_MANAGE,
            ]
        ),
    )


def test_unassigned_agent_is_concealed_and_visible_missing_action_is_forbidden():
    context, membership = _context()
    agent = _agent(membership.organization_id)
    scope = _assigned_scope(membership.organization_id, membership.id)
    policy = Mock()
    policy.resolve.side_effect = lambda _context, _org, permission: (
        scope if permission == PermissionKey.AGENT_READ else None
    )
    repository = Mock()
    repository.get_active_in_scope.return_value = None
    authorization = AgentAuthorization(policy=policy, repository=repository)

    with pytest.raises(HTTPException) as concealed:
        authorization.require_visible(context, agent.id)
    assert_that(concealed.value.status_code, equal_to(404))

    repository.get_active_in_scope.return_value = agent
    with pytest.raises(HTTPException) as forbidden:
        authorization.require_action(context, agent.id, PermissionKey.AGENT_UPDATE)
    assert_that(forbidden.value.status_code, equal_to(403))
