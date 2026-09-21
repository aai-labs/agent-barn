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
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import BaseModel, ConfigDict, Field

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import SharedMemoryFactRepository, SharedMemoryProvenance
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.honcho.client import (
    HonchoClient,
    HonchoError,
    workspace_id_for_pool,
)

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


class MemoryCarryOverCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_agent_ids: list[UUID] = Field(min_length=1, max_length=20, alias="targetAgentIds")


class MemoryCarryOverResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    copied: int
    # Set when the source held more than the copy limit, so the caller learns the
    # carry-over was partial *before* deleting the Agent rather than afterwards.
    truncated: bool = False
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


def _facet_for_peer(peer: str, count: int, agent_name: str, ai_peer_name: str) -> MemoryFacet:
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

    Hermes: set by us in `build_honcho_config` (`builders/hermes.py`), one peer
    name per Agent. OpenClaw: fixed by the plugin as `agent-{logical id}`
    (Honcho's own integration docs), where the logical id is
    `openclaw_logical_agent_id`. Neither convention is ours to invent; both are
    read from what the builders emit or what Honcho's docs specify.
    """
    if agent.agent_type == AgentType.HERMES:
        return f"agent-{agent.name}"
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
class MemorySharingService:
    agent_authorization: AgentAuthorization
    honcho: HonchoClient
    config: Config
    provenance: SharedMemoryFactRepository

    def _record_provenance(
        self, created: list[dict], *, target_agent_id: UUID, source_agent_id: UUID, context: CurrentUserContext
    ) -> None:
        """Record where each shared conclusion came from, without letting that fail
        the share. By the time this runs the fact is already in the destination's
        memory, so a provenance-write hiccup must not turn a successful share into a
        500 — the memory simply shows unbadged, and that is recoverable, whereas a
        raised error here reports failure for a change that happened."""
        for conclusion in created:
            try:
                self.provenance.record(
                    conclusion_id=str(conclusion.get("id")),
                    target_agent_id=target_agent_id,
                    source_agent_id=source_agent_id,
                    shared_by_user_id=getattr(context.user, "id", None),
                )
            except Exception:
                logger.warning(
                    "Shared fact %s into agent %s but could not record its provenance",
                    conclusion.get("id"),
                    target_agent_id,
                    exc_info=True,
                )

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
            if not memory_active(target_agent, honcho_enabled=self.config.honcho_enabled):
                results.append(
                    SharedFactTargetResult(
                        agentId=target_agent_id, shared=False, error="Agent is not in a memory group."
                    )
                )
                continue
            try:
                created = self.honcho.share_fact(
                    memory_workspace_for_agent(target_agent),
                    ai_peer_name_for_agent(target_agent),
                    payload.content,
                )
                # After Honcho confirms each conclusion. Provenance is best-effort:
                # the fact is already stored, so a failed row must not fail the share.
                self._record_provenance(
                    created, target_agent_id=target_agent.id, source_agent_id=source_agent_id, context=context
                )
                results.append(SharedFactTargetResult(agentId=target_agent_id, shared=True))
            except HonchoError as exc:
                results.append(SharedFactTargetResult(agentId=target_agent_id, shared=False, error=str(exc)))
        return SharedFactResult(results=results)

    # Copies a source pool's conclusions into other Agents' pools — the one path
    # that crosses the workspace boundary between distinct pools. Deliberately
    # bounded: a rescue-sized batch, not a migration tool.
    MAX_CARRY_OVER = 500

    def carry_over(
        self, source_agent_id: UUID, payload: MemoryCarryOverCreate, context: CurrentUserContext
    ) -> MemoryCarryOverResult:
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Memory sharing requires Honcho-backed memory to be enabled.",
            )
        # Reading the source's memory, not just naming it, so this needs the memory
        # read grant rather than the plain agent read that sharing a typed-in fact takes.
        source = self.agent_authorization.require_action(context, source_agent_id, PermissionKey.AGENT_MEMORY_READ)
        if not memory_active(source, honcho_enabled=self.config.honcho_enabled):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This agent is not in a memory group, so it has no memory to carry over.",
            )
        targets = [
            self.agent_authorization.require_action(context, target_id, PermissionKey.AGENT_MEMORY_MANAGE)
            for target_id in payload.target_agent_ids
        ]

        try:
            items = self.honcho.list_all_conclusions(memory_workspace_for_agent(source), limit=self.MAX_CARRY_OVER + 1)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        truncated = len(items) > self.MAX_CARRY_OVER
        contents = [str(i.get("content") or "") for i in items[: self.MAX_CARRY_OVER]]
        contents = [c for c in contents if c]

        results: list[SharedFactTargetResult] = []
        copied = 0
        for target in targets:
            if not memory_active(target, honcho_enabled=self.config.honcho_enabled):
                results.append(
                    SharedFactTargetResult(agentId=target.id, shared=False, error="Agent is not in a memory group.")
                )
                continue
            workspace = memory_workspace_for_agent(target)
            peer = ai_peer_name_for_agent(target)
            failure: str | None = None
            for content in contents:
                try:
                    created = self.honcho.share_fact(workspace, peer, content)
                except HonchoError as exc:
                    # Stop at the first failure for this destination: the rest would
                    # almost certainly fail the same way, and reporting a partial
                    # count is more useful than a long stall.
                    failure = str(exc)
                    break
                self._record_provenance(
                    created, target_agent_id=target.id, source_agent_id=source_agent_id, context=context
                )
                copied += 1
            results.append(SharedFactTargetResult(agentId=target.id, shared=failure is None, error=failure))
        return MemoryCarryOverResult(copied=copied, truncated=truncated, results=results)


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
        workspace = memory_workspace_for_agent(agent)
        ai_peer = ai_peer_name_for_agent(agent)
        # "mine" scopes to this Agent as observer; "pool" leaves observer open so
        # every member's conclusions are included.
        observer = ai_peer if scope == "mine" else None
        try:
            items, total = self.honcho.list_conclusions(
                workspace, page=page, size=size, observer=observer, observed=observed
            )
            # Facets describe the whole workspace, so they are computed only for the
            # unfiltered view — asking for them under a filter would be redundant work.
            facets = self._memory_facets(workspace, observer, ai_peer, agent.name) if observed is None else []
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        shared = self.provenance.find_for_conclusions([str(i.get("id")) for i in items])
        return MemoryPage(
            items=[_to_memory_item(i, shared.get(str(i.get("id")))) for i in items],
            total=total,
            page=page,
            size=size,
            facets=facets,
        )

    def _memory_facets(self, workspace: str, observer: str | None, ai_peer: str, agent_name: str) -> list[MemoryFacet]:
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
        workspace = self._require_pool(agent)
        try:
            self.honcho.delete_conclusion(workspace, memory_id)
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
        workspace = self._require_pool(agent)
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
        if not memory_active(agent, honcho_enabled=self.config.honcho_enabled):
            return []
        workspace = memory_workspace_for_agent(agent)
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
