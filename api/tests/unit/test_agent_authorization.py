from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4, uuid7

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import OrganizationRole, PermissionKey
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser


def _context(role: OrganizationRole = OrganizationRole.MEMBER):
    organization_id = uuid7()
    user = User(
        email=f"{uuid7()}@example.com",
        hashed_password="hashed",
        email_verified_at=datetime.now(timezone.utc),
    )
    membership = OrganizationUser(
        user_id=user.id,
        organization_id=organization_id,
        role=role,
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
        agent_template_id=uuid4(),
        status=status,
    )


def test_editor_effective_actions_come_from_agent_access_role_permissions():
    context, membership = _context()
    agent = _agent(membership.organization_id)
    repository = Mock()
    repository.find_agent_permissions.return_value = {
        agent.id: {
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_LIFECYCLE_MANAGE,
            PermissionKey.AGENT_SECRET_MANAGE,
        }
    }
    authorization = AgentAuthorization(policy=Mock(), repository=repository)

    actions = authorization.allowed_actions(context, [agent])[agent.id]

    assert_that(
        actions,
        equal_to(
            [
                PermissionKey.AGENT_READ,
                PermissionKey.AGENT_UPDATE,
                PermissionKey.AGENT_LIFECYCLE_MANAGE,
                PermissionKey.AGENT_SECRET_MANAGE,
            ]
        ),
    )


def test_explicit_owner_can_manage_access_regardless_of_creator_provenance():
    context, membership = _context()
    agent = _agent(
        membership.organization_id,
        creator_id=uuid7(),
        status=AgentStatus.RUNNING,
    )
    repository = Mock()
    repository.find_agent_permissions.return_value = {
        agent.id: {
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_DELETE,
            PermissionKey.AGENT_LIFECYCLE_MANAGE,
            PermissionKey.AGENT_ACCESS_MANAGE,
            PermissionKey.AGENT_SECRET_MANAGE,
        }
    }
    authorization = AgentAuthorization(policy=Mock(), repository=repository)

    actions = authorization.allowed_actions(context, [agent])[agent.id]

    assert_that(
        actions,
        equal_to(
            [
                PermissionKey.AGENT_READ,
                PermissionKey.AGENT_DELETE,
                PermissionKey.AGENT_LIFECYCLE_MANAGE,
                PermissionKey.AGENT_ACCESS_MANAGE,
            ]
        ),
    )


def test_organization_admin_has_implicit_owner_actions():
    context, membership = _context(OrganizationRole.ADMIN)
    agent = _agent(membership.organization_id)
    repository = Mock()
    authorization = AgentAuthorization(policy=Mock(), repository=repository)

    actions = authorization.allowed_actions(context, [agent])[agent.id]

    assert PermissionKey.AGENT_DELETE in actions
    assert PermissionKey.AGENT_ACCESS_MANAGE in actions
    repository.find_agent_permissions.assert_not_called()


def test_unassigned_agent_is_concealed_and_visible_missing_action_is_forbidden():
    context, membership = _context()
    agent = _agent(membership.organization_id)
    repository = Mock()
    repository.get_active_in_scope.return_value = None
    authorization = AgentAuthorization(policy=Mock(), repository=repository)

    with pytest.raises(HTTPException) as concealed:
        authorization.require_visible(context, agent.id)
    assert_that(concealed.value.status_code, equal_to(404))

    repository.get_active_in_scope.side_effect = [agent, None]
    with pytest.raises(HTTPException) as forbidden:
        authorization.require_action(context, agent.id, PermissionKey.AGENT_UPDATE)
    assert_that(forbidden.value.status_code, equal_to(403))
