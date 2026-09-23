"""Agent memory: pool-shared, plus explicit cross-Agent sharing.

Agents in the same memory group share one Honcho workspace, so within a group
memory is shared automatically (that's the point of a pool). This module holds
the read/manage surface over that shared memory (list/search/forget/correct,
scoped to the pool) and the resolvers that map an Agent to its pool workspace and
peer identity.

It also keeps the older explicit-sharing paths (share_fact, carry_over): writing
a specific fact into named Agents' pools. In the pool model within-group sharing
is automatic, so these are largely superseded — they remain for writing across
pools or seeding memory, and are gated on the target being in a group.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import BaseModel, ConfigDict, Field

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.repository import PoolMemoryProvenance, SharedPoolMemoryFactRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.honcho.client import (
    HonchoClient,
    HonchoError,
    workspace_id_for_pool,
)

logger = logging.getLogger(__name__)


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
    # Set only for a memory shared in from another pool (group). The id, not the
    # name: the client resolves the name from its groups list, so the read path
    # never crosses into the memory_groups domain. `shared_at` is when it was
    # shared; a `None` group id with `shared_at` set means the source group is gone.
    shared_at: str | None = Field(default=None, alias="sharedAt")
    shared_from_group_id: UUID | None = Field(default=None, alias="sharedFromGroupId")


class MemoryFacet(BaseModel):
    """One peer the memory can be filtered to, with its own count.

    `peer` is the raw Honcho id the client sends back to filter; `label` is what
    the tab shows. Counts are the peer's real totals, so a facet chip means the
    same number whichever page is open."""

    model_config = ConfigDict(populate_by_name=True)

    peer: str
    label: str
    count: int
    # The Agent's model of itself, versus a person it has talked to. The tab uses
    # it to order facets and to drop the redundant per-row "about whom" label.
    is_self: bool = Field(alias="isSelf")


class MemoryPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[MemoryItemRead]
    total: int
    page: int
    size: int
    # Every peer the memory can be filtered to, each with its real count. Absent
    # (empty) when a specific peer is being viewed — the facets describe the whole
    # workspace, so they are computed only for the unfiltered "Everyone" view.
    facets: list[MemoryFacet] = Field(default_factory=list)


class MemoryItemUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# Peers grow with the number of people an Agent talks to. Searching every pair is
# quadratic, so the fan-out is capped: a search box must stay a search box.
_MAX_SEARCH_PEERS = 8

# The pair searches are independent, so they run concurrently rather than serially
# (serial made a search tens of seconds). Bounded so a wide pool does not open a
# burst of embedding calls at the model backend all at once.
_SEARCH_CONCURRENCY = 8


def _to_memory_item(raw: dict, pool_shared: PoolMemoryProvenance | None = None) -> MemoryItemRead:
    return MemoryItemRead(
        id=str(raw.get("id")),
        content=str(raw.get("content") or ""),
        observer=str(raw.get("observer_id") or ""),
        observed=str(raw.get("observed_id") or ""),
        level=str(raw.get("level") or "explicit"),
        createdAt=raw.get("created_at"),
        sharedAt=pool_shared.shared_at.isoformat() if pool_shared and pool_shared.shared_at else None,
        sharedFromGroupId=pool_shared.source_group_id if pool_shared else None,
    )


def _facet_for_peer(peer: str, count: int, agent_name: str, ai_peer_name: str | None) -> MemoryFacet:
    """Turn a raw Honcho peer id into a facet the tab can show.

    The three cases mirror how memory is actually keyed. The AI peer is the
    Agent's model of itself. `owner` is OpenClaw's id for whoever is talking to
    the Agent through the app when no sender identity is attached — a person, not
    headless traffic, so it reads as "you". Everything else is a named
    correspondent (a Slack user id, say), shown as-is."""
    if peer == ai_peer_name:
        return MemoryFacet(peer=peer, label=f"What {agent_name} knows", count=count, isSelf=True)
    if peer == "owner":
        return MemoryFacet(peer=peer, label="About you", count=count, isSelf=False)
    return MemoryFacet(peer=peer, label=f"About {peer}", count=count, isSelf=False)


def openclaw_logical_agent_id(agent: Agent) -> str:
    """The OpenClaw logical agent id used as this Agent's memory identity.

    OpenClaw derives its Honcho peer as `agent-<logical id>`. Historically every
    Agent used the implicit default "main", so all OpenClaw Agents collided on
    `agent-main` — harmless when each had its own workspace, but in a shared
    memory pool their peers must be distinct or their memory is indistinguishable.
    The Agent's own id is stable and unique, so it is the logical id: the builder
    declares an explicit agent entry keyed by it (`builders/openclaw.py`), and
    the plugin then names the peer `agent-<id>`.
    """
    return str(agent.id)


def ai_peer_name_for_agent(agent: Agent) -> str:
    """The Honcho peer that represents an Agent's own runtime, not its users.

    Both runtimes name it `agent-<agent id>`. The id is stable and URL-safe, so a
    rename never orphans the Agent's memory and Honcho never renormalizes the peer
    — a name like "Ada the Assistant" would be stored as `agent-Ada-the-Assistant`,
    which a name-based read filter would then miss. OpenClaw's plugin already
    derives this from `openclaw_logical_agent_id`; Hermes gets the same value
    written into honcho.json by `build_honcho_config`, so read and write agree.
    """
    return f"agent-{openclaw_logical_agent_id(agent)}"


def memory_active(agent: Agent, *, honcho_enabled: bool) -> bool:
    """Whether the shared memory layer is on for this Agent right now.

    Two gates: the infra flag (is Honcho deployed at all) and the Agent's
    membership in a memory group. Membership is the opt-in — removing the Agent
    from its group flips this to False, so the next start gives it no pool config:
    it loses read/write access while its past contributions stay in the pool.
    Nothing here deletes memory.
    """
    return honcho_enabled and agent.memory_group_id is not None


def memory_pool_id_for_agent(agent: Agent) -> str:
    """The id of the memory pool an Agent's memory lives in — its group's id.

    Only meaningful when the Agent belongs to a group; callers gate on
    `memory_active` first. Every Agent in the same group shares one Honcho
    workspace (`af-pool-<group id>`) and therefore one shared memory.
    """
    return str(agent.memory_group_id)


def memory_workspace_for_agent(agent: Agent) -> str:
    """The shared Honcho workspace an opted-in Agent reads and writes.

    Pool-derived, so several Agents resolve to the same workspace and see each
    other's memory. Callers gate on `honcho_enabled` and the Agent's opt-in
    (`memory_enabled`) before using this — it does not itself check either.
    """
    return workspace_id_for_pool(memory_pool_id_for_agent(agent))


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
    pool_provenance: SharedPoolMemoryFactRepository

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

    def _require_pool(self, agent: Agent) -> str:
        """The Agent's pool workspace, or a 409 if it has no shared memory.

        Used by the write paths (forget/correct): there is nothing to manage when
        the Agent belongs to no group.
        """
        if not memory_active(agent, honcho_enabled=self.config.honcho_enabled):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This agent is not in a memory group, so it has no shared memory.",
            )
        return memory_workspace_for_agent(agent)

    def list_memory(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        *,
        page: int,
        size: int,
        observed: str | None = None,
        scope: str = "pool",
    ) -> MemoryPage:
        """One page of memory from the Agent's pool, optionally filtered to one peer.

        `scope="pool"` (default) shows what the whole pool knows — every member's
        conclusions, so the Agent sees what the others learned. `scope="mine"`
        narrows to what THIS Agent concluded (observer = its own peer). An Agent
        with no group has no shared memory, so the page is empty.
        """
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_READ, context)
        if not memory_active(agent, honcho_enabled=self.config.honcho_enabled):
            return MemoryPage(items=[], total=0, page=page, size=size, facets=[])
        ai_peer = ai_peer_name_for_agent(agent)
        # "mine" scopes to this Agent as observer; "pool" leaves observer open so
        # every member's conclusions are included.
        observer = ai_peer if scope == "mine" else None
        return self.list_memory_for_workspace(
            memory_workspace_for_agent(agent),
            page=page,
            size=size,
            observed=observed,
            observer=observer,
            ai_peer=ai_peer,
            agent_name=agent.name,
        )

    def list_memory_for_workspace(
        self,
        workspace: str,
        *,
        page: int,
        size: int,
        observed: str | None = None,
        observer: str | None = None,
        ai_peer: str | None = None,
        agent_name: str = "",
    ) -> MemoryPage:
        """One page of a pool workspace's memory, badged with provenance.

        Workspace-keyed so the per-Agent view (Agent → its pool) and the group view
        (group → its pool) share one implementation. `observer` scopes the query
        (None = the whole pool); `ai_peer`/`agent_name` only affect facet labelling
        and are omitted for the group view, which has no single self-model peer.
        """
        try:
            items, total = self.honcho.list_conclusions(
                workspace, page=page, size=size, observer=observer, observed=observed
            )
            # Facets describe the whole workspace, so they are computed only for the
            # unfiltered view — asking for them under a filter would be redundant work.
            facets = self._memory_facets(workspace, observer, ai_peer, agent_name) if observed is None else []
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        ids = [str(i.get("id")) for i in items]
        pool_shared = self.pool_provenance.find_for_conclusions(ids)
        return MemoryPage(
            items=[_to_memory_item(i, pool_shared.get(str(i.get("id")))) for i in items],
            total=total,
            page=page,
            size=size,
            facets=facets,
        )

    def _memory_facets(
        self, workspace: str, observer: str | None, ai_peer: str | None, agent_name: str
    ) -> list[MemoryFacet]:
        """The peers the pool has memory about, each with its real count.

        `observer` scopes the count (None = the whole pool's conclusions about the
        peer; the Agent's own peer = just what this Agent concluded). `ai_peer`
        always labels the Agent's own peer as its self-model, whichever scope. The
        self-model sorts first, then the rest by size.
        """
        facets: list[MemoryFacet] = []
        for peer in self.honcho.list_peers(workspace):
            _, count = self.honcho.list_conclusions(workspace, page=1, size=1, observer=observer, observed=peer)
            if count:
                facets.append(_facet_for_peer(peer, count, agent_name, ai_peer))
        facets.sort(key=lambda f: (not f.is_self, -f.count, f.label))
        return facets

    def forget(self, agent_id: UUID, memory_id: str, context: CurrentUserContext) -> None:
        # Not agent.update: removing what an Agent knows changes what it believes,
        # which is a different power from changing how it is configured.
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        self.forget_in_workspace(self._require_pool(agent), memory_id)

    def forget_in_workspace(self, workspace: str, memory_id: str) -> None:
        """Delete one conclusion from a pool workspace and drop its provenance."""
        try:
            self.honcho.delete_conclusion(workspace, memory_id)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        self.pool_provenance.forget(memory_id)

    def correct(
        self, agent_id: UUID, memory_id: str, payload: MemoryItemUpdate, context: CurrentUserContext
    ) -> MemoryItemRead:
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        return self.correct_in_workspace(self._require_pool(agent), memory_id, payload)

    def correct_in_workspace(self, workspace: str, memory_id: str, payload: MemoryItemUpdate) -> MemoryItemRead:
        """Replace one memory's content in a pool workspace.

        Honcho has no update endpoint, so this deletes and recreates. Two
        consequences are deliberately visible rather than hidden: the item gets a
        new id, and the replacement is always `explicit` because create cannot set
        a level — a corrected deduction stops being labelled a deduction.
        """
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
        self.pool_provenance.carry_forward(memory_id, new_id)
        return _to_memory_item(created, self.pool_provenance.find_for_conclusions([new_id]).get(new_id))

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
        if not memory_active(agent, honcho_enabled=self.config.honcho_enabled):
            return []
        return self.search_memory_for_workspace(memory_workspace_for_agent(agent), query, limit=limit)

    def search_memory_for_workspace(self, workspace: str, query: str, *, limit: int) -> list[MemoryItemRead]:
        """Semantic search across a pool workspace, fanning out over its peer pairs.

        Workspace-keyed so the per-Agent and group views share it. Honcho searches
        one (observer, observed) collection at a time — the vectors are stored per
        pair — so this fans out over the pairs and merges. The pairs are independent
        (each is a round-trip plus a vector query), so they run concurrently rather
        than serially, which is what made search take tens of seconds. Bounded by
        `_MAX_SEARCH_PEERS` (how many pairs) and `_SEARCH_CONCURRENCY` (how many at
        once). Results keep pair order, then dedupe, so output is deterministic.
        """
        peers = self.honcho.list_peers(workspace)[:_MAX_SEARCH_PEERS]
        pairs = [(observer, observed) for observer in peers for observed in peers]
        if not pairs:
            return []
        try:
            with ThreadPoolExecutor(max_workers=_SEARCH_CONCURRENCY) as pool:
                pages = list(
                    pool.map(
                        lambda pair: self.honcho.search_conclusions(
                            workspace, query=query, observer=pair[0], observed=pair[1], top_k=limit
                        ),
                        pairs,
                    )
                )
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        results: list[dict] = []
        seen: set[str] = set()
        for page in pages:
            for item in page:
                item_id = str(item.get("id"))
                if item_id not in seen:
                    seen.add(item_id)
                    results.append(item)
        return [_to_memory_item(i) for i in results[:limit]]

    def _find(self, workspace: str, memory_id: str) -> dict | None:
        """Locate one memory so a correction can preserve its peer pair."""
        return self.honcho.find_conclusion(workspace, memory_id)


@inject
@singleton
@dataclass
class SharedPoolMemoryService:
    """Records where a pool's shared-in memories came from.

    The provenance table lives in this (agents) domain so the memory read path can
    join it without a cross-domain cycle. `memory_groups` performs the cross-pool
    copy (it owns the group authz and the pool workspaces) and calls this to badge
    the result — `memory_groups → agents` is the one allowed direction.
    """

    provenance: SharedPoolMemoryFactRepository

    def record_share(
        self,
        created: list[dict],
        *,
        source_group_id: UUID,
        target_group_id: UUID,
        shared_by_user_id: UUID | None,
    ) -> None:
        """Badge each shared conclusion with its origin group, best-effort.

        By the time this runs the fact is already in the destination pool, so a
        provenance-write hiccup must not turn a successful share into a 500 — the
        memory simply shows unbadged, which is recoverable, whereas raising here
        reports failure for a change that happened."""
        for conclusion in created:
            try:
                self.provenance.record(
                    conclusion_id=str(conclusion.get("id")),
                    target_group_id=target_group_id,
                    source_group_id=source_group_id,
                    shared_by_user_id=shared_by_user_id,
                )
            except Exception:
                logger.warning(
                    "Shared conclusion %s into pool %s but could not record its provenance",
                    conclusion.get("id"),
                    target_group_id,
                    exc_info=True,
                )
