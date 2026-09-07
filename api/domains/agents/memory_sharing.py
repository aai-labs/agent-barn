"""Explicit cross-Agent memory sharing.

Honcho workspaces are isolated per Agent by default (see the ADR at
docs/adr/2026-09-03-honcho-backed-agent-memory.md), and nothing crosses that
boundary automatically. This is the one deliberate crossing: an operator picks a
specific fact and an explicit set of destination Agents, and it is written into
each destination's Honcho workspace as a conclusion on that Agent's own
self-model, which is where its recall looks. Nothing is read out of the source
Agent — "source" here is audit context, the operator's own knowledge is what
supplies the content.

Honcho has no cross-workspace sharing and cannot grow one: `workspace_name`
participates in nearly every composite foreign key, so isolation is a schema
property rather than a policy. Copying into the destination is therefore the only
mechanism available, not a shortcut around a better one.

Both source and every destination must be a currently active Agent. Retaining
a deleted Agent's Honcho workspace (see the ADR) makes promoting from it a
reasonable future ask, but doing so needs deleted-Agent read authorization the
`AgentAuthorization` layer does not have yet, so it is out of scope here.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import BaseModel, ConfigDict, Field

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import AgentRepository, SharedMemoryFactRepository, SharedMemoryProvenance
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import HonchoClient, HonchoError, workspace_id_for_agent

logger = logging.getLogger(__name__)


class SharedFactCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(min_length=1, max_length=4000)
    target_agent_ids: list[UUID] = Field(min_length=1, max_length=20, alias="targetAgentIds")


class SharedFactTargetResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: UUID = Field(alias="agentId")
    shared: bool
    error: str | None = None


class SharedFactResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    results: list[SharedFactTargetResult]


class MemoryItemRead(BaseModel):
    """One thing an Agent concluded, as shown to an owner.

    `observer`/`observed` are Honcho peers, not users: memory is stored per
    (observer, observed) pair, so the same Agent holds a separate view of each
    person it talks to plus a model of itself.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    content: str
    observer: str
    observed: str
    # "explicit" is something stated; "deductive" is something Honcho inferred.
    level: str
    created_at: str | None = Field(default=None, alias="createdAt")
    # Set only for a memory another Agent shared in. Honcho stores it on this
    # Agent's own self-model, identically to something it concluded itself, so
    # without this the view cannot tell the two apart. `None` means self-derived;
    # a name that is `None` while `shared_at` is set means the source Agent is gone.
    shared_from: str | None = Field(default=None, alias="sharedFrom")
    shared_at: str | None = Field(default=None, alias="sharedAt")


class MemoryPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[MemoryItemRead]
    total: int
    page: int
    size: int


class OrganizationAgentMemoryRead(BaseModel):
    """One Agent's line in the Organization-wide memory directory."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: UUID = Field(alias="agentId")
    agent_name: str = Field(alias="agentName")
    agent_type: str = Field(alias="agentType")
    # Deleted Agents keep their memory (see the ADR), which is the reason this
    # view exists: without it that memory is personal data nobody can reach.
    deleted: bool
    # None means Honcho could not be reached for this Agent. Distinct from 0,
    # which means the workspace exists and holds nothing — reporting an
    # unreachable workspace as empty would read as "this Agent learned nothing".
    memory_count: int | None = Field(default=None, alias="memoryCount")


class OrganizationMemoryRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agents: list[OrganizationAgentMemoryRead]
    total_memories: int = Field(alias="totalMemories")
    # True when at least one Agent's count is None, so the total is a floor
    # rather than a figure — the UI says so rather than presenting it as exact.
    partial: bool = False


class MemoryItemUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# Peers grow with the number of people an Agent talks to. Searching every pair is
# quadratic, so the fan-out is capped: a search box must stay a search box.
_MAX_SEARCH_PEERS = 8


def _to_memory_item(raw: dict, shared: SharedMemoryProvenance | None = None) -> MemoryItemRead:
    return MemoryItemRead(
        id=str(raw.get("id")),
        content=str(raw.get("content") or ""),
        observer=str(raw.get("observer_id") or ""),
        observed=str(raw.get("observed_id") or ""),
        level=str(raw.get("level") or "explicit"),
        createdAt=raw.get("created_at"),
        sharedFrom=shared.source_agent_name if shared else None,
        sharedAt=shared.shared_at.isoformat() if shared and shared.shared_at else None,
    )


def ai_peer_name_for_agent(agent: Agent) -> str:
    """The Honcho peer that represents an Agent's own runtime, not its users.

    Hermes: set by us in `build_honcho_config` (`builders/hermes.py`), one peer
    name per Agent. OpenClaw: fixed by the plugin as `agent-{openclaw_agent_id}`
    (Honcho's own integration docs), and every Agent's OpenClaw config names its
    one logical agent "main" (`builders/openclaw.py`), so this is `agent-main` for
    every OpenClaw Agent — workspace isolation is what separates them, not the
    peer name. Neither convention is ours to invent; both are read from what the
    builders already emit or what Honcho's docs specify.
    """
    if agent.agent_type == AgentType.HERMES:
        return f"agent-{agent.name}"
    return "agent-main"


@inject
@singleton
@dataclass
class MemorySharingService:
    agent_authorization: AgentAuthorization
    honcho: HonchoClient
    config: Config
    provenance: SharedMemoryFactRepository

    def share_fact(
        self, source_agent_id: UUID, payload: SharedFactCreate, context: CurrentUserContext
    ) -> SharedFactResult:
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Memory sharing requires Honcho-backed memory to be enabled.",
            )
        # Read access on the source: it is audit context for the fact, not a data
        # source, but referencing an Agent the caller cannot see is still a leak.
        self.agent_authorization.require_action(context, source_agent_id, PermissionKey.AGENT_READ)

        results: list[SharedFactTargetResult] = []
        for target_agent_id in payload.target_agent_ids:
            # Update, not read: this materially changes what the destination
            # Agent knows, so it needs the same permission editing it would.
            # Writing into a destination's memory is the same power as editing it
            # directly, so it takes the same permission rather than agent.update.
            target_agent = self.agent_authorization.require_action(
                context, target_agent_id, PermissionKey.AGENT_MEMORY_MANAGE
            )
            try:
                created = self.honcho.share_fact(
                    workspace_id_for_agent(target_agent.id),
                    ai_peer_name_for_agent(target_agent),
                    payload.content,
                )
                # Only after Honcho confirms: a row for a conclusion that was never
                # created would badge whichever unrelated memory later takes that id.
                self.provenance.record(
                    conclusion_id=str(created.get("id")),
                    target_agent_id=target_agent.id,
                    source_agent_id=source_agent_id,
                    shared_by_user_id=getattr(context.user, "id", None),
                )
                results.append(SharedFactTargetResult(agentId=target_agent_id, shared=True))
            except HonchoError as exc:
                results.append(SharedFactTargetResult(agentId=target_agent_id, shared=False, error=str(exc)))
        return SharedFactResult(results=results)


@inject
@singleton
@dataclass
class AgentMemoryService:
    """Read and curate what an Agent has learned.

    Honcho holds the memory; this exists so an owner can see and correct it
    without being handed the raw workspace, and so every read and write goes
    through the same Agent Access check as any other subordinate resource.
    """

    agent_authorization: AgentAuthorization
    honcho: HonchoClient
    config: Config
    provenance: SharedMemoryFactRepository
    permission_policy: PermissionPolicy
    agent_repository: AgentRepository

    def _require(self, agent_id: UUID, permission: PermissionKey, context: CurrentUserContext) -> Agent:
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent memory requires Honcho-backed memory to be enabled.",
            )
        # Deleting an Agent retains its Honcho workspace, so its memory has to stay
        # reachable — otherwise it is personal data nobody can view, search, or
        # erase. Reaching a deleted Agent needs organization-wide visibility.
        return self.agent_authorization.require_action_allowing_deleted(context, agent_id, permission)

    def list_organization_memory(self, context: CurrentUserContext) -> OrganizationMemoryRead:
        """Every Agent in the Organization that could hold memory, with its size.

        A directory rather than a merged stream of memories: Honcho keyed every
        workspace by Agent, and nothing reads across workspaces, so a combined
        list would query every Agent on every page and paginate across sources
        that do not share an order. Counting is one cheap call per Agent, and the
        per-Agent view already handles reading.

        Deleted Agents are included deliberately — their memory is retained (see
        the ADR), so this is the only place it can be found.
        """
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent memory requires Honcho-backed memory to be enabled.",
            )
        org_id = context.require_current_user_organization().organization_id
        # Organization-wide rather than per-Agent: this lists Agents the caller
        # may hold no individual grant on, including deleted ones.
        self.permission_policy.require_organization(
            context,
            org_id,
            PermissionKey.AGENT_MEMORY_READ,
            detail="You don't have permission to view this organization's agent memory.",
        )

        entries: list[OrganizationAgentMemoryRead] = []
        total = 0
        partial = False
        for agent in self.agent_repository.find_all_for_org(org_id):
            try:
                _, count = self.honcho.list_conclusions(workspace_id_for_agent(agent.id), page=1, size=1)
            except HonchoError:
                # One unreachable workspace must not blank the whole directory:
                # the other Agents' counts are still true.
                logger.warning("Could not read memory size for agent %s", agent.id, exc_info=True)
                count = None
                partial = True
            else:
                total += count
            entries.append(
                OrganizationAgentMemoryRead(
                    agentId=agent.id,
                    agentName=agent.name,
                    # The column is a plain string, so SQLModel hands back a str
                    # rather than the enum. Normalising accepts either.
                    agentType=AgentType(agent.agent_type).value,
                    deleted=agent.deleted_at is not None,
                    memoryCount=count,
                )
            )
        # Largest first: the reason to open this page is usually to find where
        # memory has accumulated. Unreachable Agents sort last rather than as 0.
        entries.sort(key=lambda e: (e.memory_count is None, -(e.memory_count or 0), e.agent_name))
        return OrganizationMemoryRead(agents=entries, totalMemories=total, partial=partial)

    def list_memory(self, agent_id: UUID, context: CurrentUserContext, *, page: int, size: int) -> MemoryPage:
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_READ, context)
        try:
            items, total = self.honcho.list_conclusions(workspace_id_for_agent(agent.id), page=page, size=size)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        shared = self.provenance.find_for_conclusions([str(i.get("id")) for i in items])
        return MemoryPage(
            items=[_to_memory_item(i, shared.get(str(i.get("id")))) for i in items],
            total=total,
            page=page,
            size=size,
        )

    def forget(self, agent_id: UUID, memory_id: str, context: CurrentUserContext) -> None:
        # Not agent.update: removing what an Agent knows changes what it believes,
        # which is a different power from changing how it is configured.
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        try:
            self.honcho.delete_conclusion(workspace_id_for_agent(agent.id), memory_id)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        self.provenance.forget(memory_id)

    def correct(
        self, agent_id: UUID, memory_id: str, payload: MemoryItemUpdate, context: CurrentUserContext
    ) -> MemoryItemRead:
        """Replace one memory's content.

        Honcho has no update endpoint, so this deletes and recreates. Two
        consequences are deliberately visible rather than hidden: the item gets a
        new id, and the replacement is always `explicit` because create cannot set
        a level — a corrected deduction stops being labelled a deduction.
        """
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        workspace = workspace_id_for_agent(agent.id)
        try:
            existing = self._find(workspace, memory_id)
            if existing is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
            self.honcho.delete_conclusion(workspace, memory_id)
            created = self.honcho.create_conclusion(
                workspace,
                content=payload.content,
                observer=str(existing.get("observer_id") or ""),
                observed=str(existing.get("observed_id") or ""),
            )
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        new_id = str(created.get("id"))
        self.provenance.carry_forward(memory_id, new_id)
        return _to_memory_item(created, self.provenance.find_for_conclusions([new_id]).get(new_id))

    def search_memory(
        self, agent_id: UUID, query: str, context: CurrentUserContext, *, limit: int
    ) -> list[MemoryItemRead]:
        """Search across everything an Agent has concluded.

        Honcho searches one (observer, observed) collection at a time — the
        vectors are stored per pair — so this fans out across the Agent's peers
        and merges. The fan-out is bounded: peers grow with the number of people
        an Agent talks to, and an unbounded one would turn a search box into a
        slow query against every pair that has ever existed.
        """
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_READ, context)
        workspace = workspace_id_for_agent(agent.id)
        try:
            peers = self.honcho.list_peers(workspace)
            results: list[dict] = []
            seen: set[str] = set()
            for observer in peers[:_MAX_SEARCH_PEERS]:
                for observed in peers[:_MAX_SEARCH_PEERS]:
                    for item in self.honcho.search_conclusions(
                        workspace, query=query, observer=observer, observed=observed, top_k=limit
                    ):
                        item_id = str(item.get("id"))
                        if item_id not in seen:
                            seen.add(item_id)
                            results.append(item)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        return [_to_memory_item(i) for i in results[:limit]]

    def _find(self, workspace: str, memory_id: str) -> dict | None:
        """Locate one memory so a correction can preserve its peer pair.

        Honcho exposes no get-by-id for conclusions, so this walks pages. Bounded
        rather than unbounded: a correction is a UI action on something the caller
        just saw, not a scan.
        """
        for page in range(1, 21):
            items, total = self.honcho.list_conclusions(workspace, page=page, size=100)
            for item in items:
                if str(item.get("id")) == memory_id:
                    return item
            if not items or page * 100 >= total:
                return None
        return None
