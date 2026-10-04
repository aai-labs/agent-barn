from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_memory.models import (
    AgentMemoryGrant,
    AgentMemoryGrantCreate,
    AgentMemoryGrantRead,
    AgentMemoryItemRead,
    AgentMemoryRead,
)
from api.domains.agent_memory.repository import AgentMemoryGrantConflictError, AgentMemoryRepository
from api.domains.agent_memory.view_client import MemoryViewClient
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy
from api.infrastructure.shared.models import PaginatedItems, Pagination

ORGANIZATION_MEMORY_DISPLAY = "Organization Memory"


@inject
@singleton
@dataclass
class AgentMemoryService:
    """Agent Memory opt-in and Memory Grants.

    Enabling memory is an Agent operation (Agent Owner authority). Memory Grants widen
    what an Agent recalls across the Organization, so they are an Organization
    operation reserved for Owners and Admins.
    """

    repository: AgentMemoryRepository
    agent_repository: AgentRepository
    authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    view_client: MemoryViewClient

    def set_memory(self, agent_id: UUID, enabled: bool, context: CurrentUserContext) -> AgentMemoryRead:
        agent = self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.AGENT_MEMORY_MANAGE,
            detail="You don't have permission to manage memory for this Agent.",
        )
        if agent.memory_enabled != enabled:
            delivery_ids = self.repository.set_enabled_with_event(
                agent.id,
                agent.organization_id,
                enabled,
                actor=resolve_actor_identity(context, agent.organization_id),
                actor_display=_actor_display(context),
            )
            self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return AgentMemoryRead(agent_id=agent.id, enabled=enabled)

    def list_memories(
        self, agent_id: UUID, search: str | None, pagination: Pagination, context: CurrentUserContext
    ) -> PaginatedItems[AgentMemoryItemRead]:
        """Saved memories written by the Agent, gated like its other conversation content.

        `activity.read` authorizes the content; `agent.memory.manage` and
        `memory.access.manage` govern settings and grants, not reading what was saved.
        """
        agent = self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.ACTIVITY_READ,
            detail="You don't have permission to view this Agent's memories.",
        )
        page = self.view_client.list_memories(
            agent.organization_id,
            agent.id,
            search=search,
            limit=pagination.size,
            offset=(pagination.page - 1) * pagination.size,
        )
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=page.total,
            items=[AgentMemoryItemRead(**item.model_dump()) for item in page.items],
        )

    def list_grants(self, organization_id: UUID, context: CurrentUserContext) -> list[AgentMemoryGrantRead]:
        self._require_manage(organization_id, context)
        return [
            AgentMemoryGrantRead(
                id=row.grant.id,
                agent_id=row.grant.agent_id,
                agent_name=row.agent_name,
                source_agent_id=row.grant.source_agent_id,
                source_agent_name=row.source_agent_name,
                created_at=row.grant.created_at,
            )
            for row in self.repository.list_grants(organization_id)
        ]

    def create_grant(
        self,
        organization_id: UUID,
        payload: AgentMemoryGrantCreate,
        context: CurrentUserContext,
    ) -> AgentMemoryGrantRead:
        scope = self._require_manage(organization_id, context)
        if payload.source_agent_id == payload.agent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An Agent already reads its own memories.",
            )
        agent = self._require_agent(payload.agent_id, scope)
        source = self._require_agent(payload.source_agent_id, scope) if payload.source_agent_id else None
        try:
            result = self.repository.create_grant_with_event(
                AgentMemoryGrant(
                    organization_id=organization_id,
                    agent_id=agent.id,
                    source_agent_id=source.id if source else None,
                    created_by_user_id=context.user.id,
                ),
                agent_name=agent.name,
                source_display=source.name if source else ORGANIZATION_MEMORY_DISPLAY,
                actor=resolve_actor_identity(context, organization_id),
                actor_display=_actor_display(context),
            )
        except AgentMemoryGrantConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return AgentMemoryGrantRead(
            id=result.grant.id,
            agent_id=agent.id,
            agent_name=agent.name,
            source_agent_id=source.id if source else None,
            source_agent_name=source.name if source else None,
            created_at=result.grant.created_at,
        )

    def revoke_grant(self, organization_id: UUID, grant_id: UUID, context: CurrentUserContext) -> None:
        self._require_manage(organization_id, context)
        grant = self.repository.get_grant(organization_id, grant_id)
        if grant is None:
            self._raise_grant_not_found(grant_id)
        agent = self.agent_repository.get_by_id(grant.agent_id)
        source = self.agent_repository.get_by_id(grant.source_agent_id) if grant.source_agent_id else None
        delivery_ids = self.repository.revoke_grant_with_event(
            grant,
            agent_name=agent.name if agent else str(grant.agent_id),
            source_display=_source_display(grant, source),
            actor=resolve_actor_identity(context, organization_id),
            actor_display=_actor_display(context),
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> AuthorizationScope:
        return self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.MEMORY_ACCESS_MANAGE,
            detail="You don't have permission to manage memory access for this organization.",
        )

    def _require_agent(self, agent_id: UUID, scope: AuthorizationScope) -> Agent:
        agent = self.agent_repository.get_active_in_scope(agent_id, scope)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        return agent

    @staticmethod
    def _raise_grant_not_found(grant_id: UUID) -> NoReturn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory grant {grant_id} not found")


def _actor_display(context: CurrentUserContext) -> str:
    return context.user.full_name or context.user.email


def _source_display(grant: AgentMemoryGrant, source: Agent | None) -> str:
    if grant.source_agent_id is None:
        return ORGANIZATION_MEMORY_DISPLAY
    return source.name if source else str(grant.source_agent_id)
