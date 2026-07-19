from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey, PermissionScope
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy

_AGENT_ACTION_PERMISSIONS: tuple[PermissionKey, ...] = (
    PermissionKey.AGENT_READ,
    PermissionKey.AGENT_UPDATE,
    PermissionKey.AGENT_DELETE,
    PermissionKey.AGENT_START,
    PermissionKey.AGENT_STOP,
    PermissionKey.AGENT_ACCESS_MANAGE,
    PermissionKey.AGENT_SECRET_MANAGE,
    PermissionKey.ACTIVITY_READ,
    PermissionKey.COST_READ,
)


@inject
@singleton
@dataclass
class AgentAuthorization:
    """Agent visibility and action policy shared by user-facing services."""

    policy: PermissionPolicy
    repository: AgentRepository

    def require_collection_scope(
        self,
        context: CurrentUserContext,
        permission: PermissionKey,
        *,
        detail: str = "You don't have permission for this organization.",
    ) -> AuthorizationScope:
        organization_id = context.require_current_user_organization().organization_id
        return self.policy.require(
            context,
            organization_id,
            permission,
            detail=detail,
        )

    def require_visible(self, context: CurrentUserContext, agent_id: UUID) -> Agent:
        organization_id = context.require_current_user_organization().organization_id
        read_scope = self.policy.resolve(
            context, organization_id, PermissionKey.AGENT_READ
        )
        if read_scope is None:
            self._raise_not_found(agent_id)
        agent = self.repository.get_active_in_scope(agent_id, read_scope)
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
        action_scope = self.policy.resolve(context, agent.organization_id, permission)
        if action_scope is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        if self.repository.get_active_in_scope(agent.id, action_scope) is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        if (
            permission == PermissionKey.AGENT_ACCESS_MANAGE
            and action_scope.scope == PermissionScope.ASSIGNED
            and agent.created_by_user_id != context.user.id
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        return action_scope

    def allowed_actions(
        self, context: CurrentUserContext, agents: list[Agent]
    ) -> dict[UUID, list[PermissionKey]]:
        if not agents:
            return {}
        organization_id = context.require_current_user_organization().organization_id
        scopes = self.policy.resolve_many(
            context, organization_id, _AGENT_ACTION_PERMISSIONS
        )
        assigned_membership_ids = {
            scope.membership_id
            for scope in scopes.values()
            if scope.scope == PermissionScope.ASSIGNED
            and scope.membership_id is not None
        }
        assigned_ids: set[UUID] = set()
        agent_ids = [agent.id for agent in agents]
        for membership_id in assigned_membership_ids:
            assigned_ids.update(
                self.repository.find_assigned_agent_ids(membership_id, agent_ids)
            )

        result: dict[UUID, list[PermissionKey]] = {}
        for agent in agents:
            actions: list[PermissionKey] = []
            for permission in _AGENT_ACTION_PERMISSIONS:
                scope = scopes.get(permission)
                if scope is None:
                    continue
                if (
                    scope.scope == PermissionScope.ASSIGNED
                    and agent.id not in assigned_ids
                ):
                    continue
                if (
                    permission == PermissionKey.AGENT_ACCESS_MANAGE
                    and scope.scope == PermissionScope.ASSIGNED
                    and agent.created_by_user_id != context.user.id
                ):
                    continue
                if not self._state_allows(agent.status, permission):
                    continue
                actions.append(permission)
            result[agent.id] = actions
        return result

    @staticmethod
    def _state_allows(status_value: AgentStatus, permission: PermissionKey) -> bool:
        if permission in (
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_SECRET_MANAGE,
        ):
            return status_value != AgentStatus.RUNNING
        if permission == PermissionKey.AGENT_START:
            return status_value != AgentStatus.RUNNING
        if permission == PermissionKey.AGENT_STOP:
            return status_value == AgentStatus.RUNNING
        return True

    @staticmethod
    def _raise_not_found(agent_id: UUID) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
