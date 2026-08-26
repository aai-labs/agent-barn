from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import (
    AGENT_OWNER_ROLE_ID,
    IMPLICIT_AGENT_OWNER_ROLES,
    SYSTEM_AGENT_ACCESS_ROLE_GRANTS,
    PermissionKey,
)
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy

_AGENT_ACTION_PERMISSIONS: tuple[PermissionKey, ...] = (
    PermissionKey.AGENT_READ,
    PermissionKey.AGENT_UPDATE,
    PermissionKey.AGENT_DELETE,
    PermissionKey.AGENT_LIFECYCLE_MANAGE,
    PermissionKey.AGENT_ACCESS_MANAGE,
    PermissionKey.AGENT_SECRET_MANAGE,
    PermissionKey.ACTIVITY_READ,
    PermissionKey.COST_READ,
)


@inject
@singleton
@dataclass
class AgentAuthorization:
    """Resolve implicit or explicit Agent authority behind one interface."""

    policy: PermissionPolicy
    repository: AgentRepository

    def _scope(
        self,
        context: CurrentUserContext,
        permission: PermissionKey,
    ) -> AuthorizationScope:
        membership = context.require_current_user_organization()
        if membership.role in IMPLICIT_AGENT_OWNER_ROLES:
            return AuthorizationScope(organization_id=membership.organization_id)
        return AuthorizationScope(
            organization_id=membership.organization_id,
            membership_id=membership.id,
            permission=permission,
            include_general_access=context.user.email_verified_at is not None,
        )

    def authorization_scope(
        self,
        context: CurrentUserContext,
        permission: PermissionKey,
    ) -> AuthorizationScope:
        """Return the repository scope for an Agent or subordinate-resource query."""
        return self._scope(context, permission)

    def require_collection_scope(
        self,
        context: CurrentUserContext,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission for this organization.",
    ) -> AuthorizationScope:
        organization_id = context.require_current_user_organization().organization_id
        if permission == PermissionKey.AGENT_CREATE:
            return self.policy.require(
                context,
                organization_id,
                permission,
                detail=detail,
            )
        return self._scope(context, permission)

    def require_visible(self, context: CurrentUserContext, agent_id: UUID) -> Agent:
        scope = self._scope(context, PermissionKey.AGENT_READ)
        agent = self.repository.get_active_in_scope(agent_id, scope)
        if agent is None:
            self._raise_not_found(agent_id)
        return agent

    def require_action(
        self,
        context: CurrentUserContext,
        agent_id: UUID,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission to perform this action.",
    ) -> Agent:
        agent = self.require_visible(context, agent_id)
        self.require_action_for_visible(context, agent, permission, detail=detail)
        return agent

    def require_action_for_visible(
        self,
        context: CurrentUserContext,
        agent: Agent,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission to perform this action.",
    ) -> AuthorizationScope:
        action_scope = self._scope(context, permission)
        if self.repository.get_active_in_scope(agent.id, action_scope) is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        return action_scope

    def allowed_actions(self, context: CurrentUserContext, agents: list[Agent]) -> dict[UUID, list[PermissionKey]]:
        if not agents:
            return {}
        membership = context.require_current_user_organization()
        if membership.role in IMPLICIT_AGENT_OWNER_ROLES:
            permissions_by_agent = {
                agent.id: set(SYSTEM_AGENT_ACCESS_ROLE_GRANTS[AGENT_OWNER_ROLE_ID]) for agent in agents
            }
        else:
            permissions_by_agent = self.repository.find_agent_permissions(
                membership.id,
                membership.organization_id,
                [agent.id for agent in agents],
                include_general_access=context.user.email_verified_at is not None,
            )

        return {
            agent.id: [
                permission
                for permission in _AGENT_ACTION_PERMISSIONS
                if permission in permissions_by_agent.get(agent.id, set())
            ]
            for agent in agents
        }

    @staticmethod
    def _raise_not_found(agent_id: UUID) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
