import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.memory_sharing import (
    AgentMemoryService,
    MemoryItemRead,
    MemoryItemUpdate,
    MemoryPage,
    SharedPoolMemoryService,
)
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.memory_groups.models import (
    MemoryGroup,
    MemoryGroupCreate,
    MemoryGroupRead,
    MemoryGroupUpdate,
    ShareMemoryItemCreate,
    ShareMemoryItemResult,
    ShareMemoryItemTargetResult,
)
from api.domains.memory_groups.repository import MemoryGroupRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import HonchoClient, HonchoError, workspace_id_for_pool

logger = logging.getLogger(__name__)

_MANAGE_DETAIL = "You don't have permission to manage memory groups."

# A shared item is written onto the destination pool's neutral "owner" peer rather
# than any member's peer: it is knowledge handed to the whole pool, not something a
# particular Agent concluded. Pool-wide recall aggregates every peer, so placement
# does not change what is recalled; it only keeps attribution honest.
_SHARE_PEER = "owner"


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
    pool_memory: SharedPoolMemoryService
    # The workspace-keyed read/curate core lives in the agents domain; group memory
    # (view/search/forget/correct) delegates to it, keyed by the pool workspace.
    memory: AgentMemoryService

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

    def names_for_org(self, org_id: UUID) -> dict[UUID, str]:
        """Group id → name for one Organization, for another domain to label rows it
        has already authorized (e.g. the cost breakdown, gated on `cost.read`). Not a
        management action, so it takes an org id rather than gating on
        `memory_group.manage` — the caller owns the access check for its own surface."""
        return {g.id: g.name for g in self.repository.find_all_for_org(org_id)}

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

    def share_item(
        self, source_group_id: UUID, payload: ShareMemoryItemCreate, context: CurrentUserContext
    ) -> ShareMemoryItemResult:
        """Copy one memory item from a source pool into other pools.

        The cross-pool equivalent of promoting a fact: within a group memory is
        already shared, so this is the one path that crosses the workspace boundary
        between distinct pools. The item is copied (Honcho has no cross-workspace
        move), badged with its origin group, and recalled pool-wide in each
        destination like any other pooled memory.
        """
        org_id = self._require_manager(context)
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Memory sharing requires Honcho-backed memory to be enabled.",
            )
        source = self._get_or_404(source_group_id, org_id)

        # Resolve and validate every target up front — a bad target is a client
        # error, not a per-item outcome — then do the writes, where a Honcho hiccup
        # against one pool is a genuine per-target result.
        targets: list[MemoryGroup] = []
        for target_id in dict.fromkeys(payload.target_group_ids):
            if target_id == source_group_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A group cannot share memory with itself.",
                )
            targets.append(self._get_or_404(target_id, org_id))

        try:
            item = self.honcho.find_conclusion(workspace_id_for_pool(source.id), payload.memory_id)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
        content = str(item.get("content") or "")
        if not content:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")

        shared_by = getattr(context.user, "id", None)
        results: list[ShareMemoryItemTargetResult] = []
        for target in targets:
            try:
                created = self.honcho.share_fact(workspace_id_for_pool(target.id), _SHARE_PEER, content)
            except HonchoError as exc:
                results.append(ShareMemoryItemTargetResult(group_id=target.id, shared=False, error=str(exc)))
                continue
            self.pool_memory.record_share(
                created, source_group_id=source.id, target_group_id=target.id, shared_by_user_id=shared_by
            )
            results.append(ShareMemoryItemTargetResult(group_id=target.id, shared=True))
        return ShareMemoryItemResult(results=results)

    # --- Group-level memory (the pool's shared memory, managed from the group) ----
    #
    # Memory belongs to the pool, not any one member, so it is viewed and curated
    # from the group itself — no member Agent required. All of this resolves the
    # pool workspace straight from the group id and delegates to the agents-domain
    # core, gated on `memory_group.manage` like the rest of this surface.

    def _require_pool_workspace(self, group_id: UUID, context: CurrentUserContext) -> str:
        org_id = self._require_manager(context)
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Memory requires Honcho-backed memory to be enabled.",
            )
        group = self._get_or_404(group_id, org_id)
        return workspace_id_for_pool(group.id)

    def list_memory(
        self, group_id: UUID, context: CurrentUserContext, *, page: int, size: int, observed: str | None = None
    ) -> MemoryPage:
        """One page of the group's pooled memory (whole pool; there is no per-Agent
        scope at the group level)."""
        workspace = self._require_pool_workspace(group_id, context)
        return self.memory.list_memory_for_workspace(workspace, page=page, size=size, observed=observed)

    def search_memory(
        self, group_id: UUID, query: str, context: CurrentUserContext, *, limit: int
    ) -> list[MemoryItemRead]:
        workspace = self._require_pool_workspace(group_id, context)
        return self.memory.search_memory_for_workspace(workspace, query, limit=limit)

    def forget_memory(self, group_id: UUID, memory_id: str, context: CurrentUserContext) -> None:
        workspace = self._require_pool_workspace(group_id, context)
        self.memory.forget_in_workspace(workspace, memory_id)

    def correct_memory(
        self, group_id: UUID, memory_id: str, payload: MemoryItemUpdate, context: CurrentUserContext
    ) -> MemoryItemRead:
        workspace = self._require_pool_workspace(group_id, context)
        return self.memory.correct_in_workspace(workspace, memory_id, payload)
