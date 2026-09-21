import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.memory_groups.models import (
    MemoryGroup,
    MemoryGroupCreate,
    MemoryGroupRead,
    MemoryGroupUpdate,
)
from api.domains.memory_groups.repository import MemoryGroupRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import HonchoClient, HonchoError, workspace_id_for_pool

logger = logging.getLogger(__name__)

_MANAGE_DETAIL = "You don't have permission to manage memory groups."


@inject
@singleton
@dataclass
class MemoryGroupService:
    """Org-scoped CRUD for memory groups (named memory pools).

    A group's id is its pool id: Agents in the group share the Honcho workspace
    `af-pool-<group id>`. Assigning Agents to a group is an Agent operation (see
    AgentService.set_memory_group) — this domain owns the group itself.
    """

    repository: MemoryGroupRepository
    permission_policy: PermissionPolicy
    honcho: HonchoClient
    config: Config
    agent_service: AgentService

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _require_manager(self, context: CurrentUserContext) -> UUID:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(
            context, org_id, PermissionKey.MEMORY_GROUP_MANAGE, detail=_MANAGE_DETAIL
        )
        return org_id

    def _get_or_404(self, group_id: UUID, org_id: UUID) -> MemoryGroup:
        group = self.repository.get_by_id_and_org(group_id, org_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory group {group_id} not found")
        return group

    def create_group(self, data: MemoryGroupCreate, context: CurrentUserContext) -> MemoryGroupRead:
        org_id = self._require_manager(context)
        group = MemoryGroup(organization_id=org_id, name=data.name)
        self.repository.save(group)
        return MemoryGroupRead.model_validate(group)

    def rename_group(self, group_id: UUID, data: MemoryGroupUpdate, context: CurrentUserContext) -> MemoryGroupRead:
        org_id = self._require_manager(context)
        group = self._get_or_404(group_id, org_id)
        group.name = data.name
        self.repository.save(group)
        return MemoryGroupRead.model_validate(group)

    def get_group(self, group_id: UUID, context: CurrentUserContext) -> MemoryGroupRead:
        org_id = self._require_manager(context)
        return MemoryGroupRead.model_validate(self._get_or_404(group_id, org_id))

    def list_groups(self, context: CurrentUserContext) -> list[MemoryGroupRead]:
        org_id = self._require_manager(context)
        return [MemoryGroupRead.model_validate(g) for g in self.repository.find_all_for_org(org_id)]

    def add_agent(self, group_id: UUID, agent_id: UUID, context: CurrentUserContext) -> None:
        """Add an Agent to a group (opt it into the group's shared memory).

        Validates the group is in the caller's org; AgentService scopes the Agent
        to the same org. Takes effect on the Agent's next start.
        """
        org_id = self._require_manager(context)
        group = self._get_or_404(group_id, org_id)
        self.agent_service.set_memory_group(agent_id, group.id, org_id)

    def remove_agent(self, group_id: UUID, agent_id: UUID, context: CurrentUserContext) -> None:
        """Remove an Agent from a group (opt-out): it loses shared-memory access on
        its next start, while its past contributions stay in the pool."""
        org_id = self._require_manager(context)
        self._get_or_404(group_id, org_id)
        self.agent_service.set_memory_group(agent_id, None, org_id)

    def delete_group(self, group_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._require_manager(context)
        group = self._get_or_404(group_id, org_id)
        # The FK is SET NULL, so deleting the row drops every member's membership
        # (they lose shared memory on their next start). Purge the shared pool
        # workspace too — a deliberate deletion, since the group and its shared
        # memory are the same thing. This is the one sanctioned path to erase a
        # pool; the per-Agent purge refuses pool workspaces.
        self.repository.delete(group)
        if self.config.honcho_enabled:
            try:
                self.honcho.delete_pool_workspace(workspace_id_for_pool(group.id))
            except HonchoError as exc:
                # Best-effort: the group is gone from the product either way. A
                # left-behind workspace is recoverable; failing the delete is not.
                logger.warning("Could not purge memory pool for deleted group %s: %s", group_id, exc)
