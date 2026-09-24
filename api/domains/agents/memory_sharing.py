"""Agent memory: the read/manage surface over a group's shared Honcho pool.

Agents in the same memory group share one Honcho workspace, so within a group
memory is shared automatically (that's the point of a pool). This module holds
the read/manage surface over that shared memory (list/search/forget/correct,
scoped to the pool and access-gated), the resolvers that map an Agent to its pool
workspace and peer identity, and the provenance record for facts shared in from
another pool (`SharedPoolMemoryService`). The cross-pool copy itself is driven by
the memory_groups domain, which owns the group authorization.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import BaseModel, ConfigDict, Field

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository, PoolMemoryProvenance, SharedPoolMemoryFactRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import (
    HonchoClient,
    HonchoError,
    workspace_id_for_pool,
)

logger = logging.getLogger(__name__)

# The human talking to an Agent is one peer per pool. Both runtimes now use
# "owner"; "operator" is the legacy Hermes name still present on pre-cutover
# memories. Facts about the person are keyed `observed = <one of these>`, which is
# what lets an Agent-wide search pin the observed side instead of crossing every
# peer with every peer.
_HUMAN_PEER = "owner"
_HUMAN_PEERS = ("owner", "operator")


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
    # The bare display name behind `label` ("you" for the human, an Agent's name
    # for an `agent-<id>` peer, else the raw peer). The tab keys its per-row "about
    # whom" label off this so an agent peer never shows as a raw id there either.
    name: str
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


# Defensive ceiling on the number of (observer, observed) pairs a single search
# fans out over. Search pins the observed side to the human peer and iterates
# observers, so under the group-size cap this is ~pool size and never near the
# ceiling. If the ceiling is somehow hit, search reports partial results rather
# than silently dropping members (the previous behaviour, a hard [:8] truncation).
_MAX_SEARCH_PAIRS = 200

# The pair searches are independent, so they run concurrently rather than serially
# (serial made a search tens of seconds). Bounded so a wide pool does not open a
# burst of embedding calls at the model backend all at once.
_SEARCH_CONCURRENCY = 8


# An `agent-<uuid>` peer id, as it appears verbatim inside a conclusion's text.
# Recall answers and shared facts sometimes bake a peer id into the content itself
# (e.g. "agent-<uuid> knows that owner likes oranges"), so the id has to be
# resolved in the text too, not only in the peer labels around it.
_AGENT_PEER_RE = re.compile(r"agent-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _humanize_agent_ids(text: str, name_by_peer: dict[str, str]) -> str:
    """Replace `agent-<uuid>` peer ids in free text with their agent's name.

    Unresolved ids are left as-is (better a raw id than a wrong name). The pattern
    is specific enough — the `agent-` prefix plus a full uuid — that it never
    touches ordinary prose."""
    if not name_by_peer:
        return text
    return _AGENT_PEER_RE.sub(lambda m: name_by_peer.get(m.group(0), m.group(0)), text)


def _to_memory_item(
    raw: dict, pool_shared: PoolMemoryProvenance | None = None, name_by_peer: dict[str, str] | None = None
) -> MemoryItemRead:
    return MemoryItemRead(
        id=str(raw.get("id")),
        content=_humanize_agent_ids(str(raw.get("content") or ""), name_by_peer or {}),
        observer=str(raw.get("observer_id") or ""),
        observed=str(raw.get("observed_id") or ""),
        level=str(raw.get("level") or "explicit"),
        createdAt=raw.get("created_at"),
        sharedAt=pool_shared.shared_at.isoformat() if pool_shared and pool_shared.shared_at else None,
        sharedFromGroupId=pool_shared.source_group_id if pool_shared else None,
    )


def _facet_for_peer(
    peer: str, count: int, agent_name: str, ai_peer_name: str | None, agent_peer_names: dict[str, str]
) -> MemoryFacet:
    """Turn a raw Honcho peer id into a facet the tab can show.

    The cases mirror how memory is actually keyed. The AI peer is the Agent's
    model of itself. `owner` is OpenClaw's id for whoever is talking to the Agent
    through the app when no sender identity is attached — a person, not headless
    traffic, so it reads as "you". Another Agent's peer (`agent-<id>`, which a
    shared pool is full of) is resolved to that Agent's name via
    `agent_peer_names`. Anything left is a named correspondent (a Slack user id,
    say), shown as-is."""
    if peer == ai_peer_name:
        return MemoryFacet(peer=peer, label=f"What {agent_name} knows", name=agent_name, count=count, isSelf=True)
    # Both are the human talking to the Agent through the app: "owner" is what both
    # runtimes use now; "operator" is the legacy Hermes name, still on pre-cutover
    # memories, so it reads as "you" too rather than showing a raw internal id.
    if peer in _HUMAN_PEERS:
        return MemoryFacet(peer=peer, label="About you", name="you", count=count, isSelf=False)
    # Another Agent in the pool: its own `agent-<id>` peer. Show its name, never
    # the raw id — the fallback to `peer` only bites for a peer we cannot resolve.
    name = agent_peer_names.get(peer, peer)
    return MemoryFacet(peer=peer, label=f"About {name}", name=name, count=count, isSelf=False)


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
    agents: AgentRepository
    permission_policy: PermissionPolicy

    def _require(self, agent_id: UUID, permission: PermissionKey, context: CurrentUserContext) -> Agent:
        if not self.config.honcho_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent memory requires Honcho-backed memory to be enabled.",
            )
        # A shared pool's memory is reachable through the group (the group memory
        # page, gated on memory_group.manage), so a deleted Agent's tab no longer
        # needs the deleted-tolerant seam — its contributions live on in the pool.
        return self.agent_authorization.require_action(context, agent_id, permission)

    def _require_group_manage(self, agent: Agent, context: CurrentUserContext) -> None:
        """Pool-wide memory (every member's conclusions) is only for someone who
        manages the group. Plain agent access sees just this Agent's own
        contributions (scope="mine"); the whole pool needs memory_group.manage,
        the same bar the group memory page enforces."""
        self.permission_policy.require_organization(
            context,
            agent.organization_id,
            PermissionKey.MEMORY_GROUP_MANAGE,
            detail="Viewing or curating the whole group's memory needs the memory-group manage permission.",
        )

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
        # The whole pool (every member's conclusions) is manager-only; plain agent
        # access is limited to this Agent's own contributions.
        if scope != "mine":
            self._require_group_manage(agent, context)
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
        name_by_peer = self._agent_names_in(items)
        return MemoryPage(
            items=[_to_memory_item(i, pool_shared.get(str(i.get("id"))), name_by_peer) for i in items],
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
        peers = self.honcho.list_peers(workspace)
        agent_peer_names = self._agent_peer_names(peers)
        facets: list[MemoryFacet] = []
        for peer in peers:
            _, count = self.honcho.list_conclusions(workspace, page=1, size=1, observer=observer, observed=peer)
            if count:
                facets.append(_facet_for_peer(peer, count, agent_name, ai_peer, agent_peer_names))
        facets.sort(key=lambda f: (not f.is_self, -f.count, f.label))
        return facets

    def _agent_names_in(self, raws: list[dict]) -> dict[str, str]:
        """`agent-<uuid>` peer -> agent name for every agent id these conclusions
        mention — in their content text as well as their observer/observed pair —
        resolved in one batch so the read path can humanize the displayed text."""
        tokens: set[str] = set()
        for raw in raws:
            tokens.update(_AGENT_PEER_RE.findall(str(raw.get("content") or "")))
            for key in ("observer_id", "observed_id"):
                value = str(raw.get(key) or "")
                if value.startswith("agent-"):
                    tokens.add(value)
        return self._agent_peer_names(list(tokens))

    def _agent_peer_names(self, peers: list[str]) -> dict[str, str]:
        """Map `agent-<uuid>` peers to their Agent's display name.

        A shared pool holds a peer per member Agent, all named `agent-<agent id>`.
        Resolving them in one batch keeps the facet list free of raw ids. A peer
        that is not an agent peer, whose id does not parse, or whose Agent is gone
        is simply absent, so the caller falls back to the raw peer id.
        """
        ids_by_peer: dict[str, UUID] = {}
        for peer in peers:
            if not peer.startswith("agent-"):
                continue
            try:
                ids_by_peer[peer] = UUID(peer[len("agent-") :])
            except ValueError:
                continue
        names = self.agents.names_by_ids(list(set(ids_by_peer.values())))
        return {peer: names[agent_id] for peer, agent_id in ids_by_peer.items() if agent_id in names}

    def _require_curate(
        self,
        agent: Agent,
        workspace: str,
        memory_id: str,
        context: CurrentUserContext,
        *,
        observer: str | None,
        observed: str | None,
    ) -> dict:
        """Locate the memory being curated and authorize the write.

        Plain `agent.memory.manage` may curate only this Agent's own contributions
        (the conclusion's observer is this Agent's peer); changing any other
        member's memory — which affects Agents the caller may not even see — needs
        `memory_group.manage`. The client-supplied `(observer, observed)` only
        scopes the lookup; authorization is checked against the stored conclusion's
        real observer, never the hint.
        """
        try:
            item = self._find(workspace, memory_id, observer=observer, observed=observed)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
        if str(item.get("observer_id") or "") != ai_peer_name_for_agent(agent):
            self._require_group_manage(agent, context)
        return item

    def forget(
        self,
        agent_id: UUID,
        memory_id: str,
        context: CurrentUserContext,
        *,
        observer: str | None = None,
        observed: str | None = None,
    ) -> None:
        # Not agent.update: removing what an Agent knows changes what it believes,
        # which is a different power from changing how it is configured.
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        workspace = self._require_pool(agent)
        self._require_curate(agent, workspace, memory_id, context, observer=observer, observed=observed)
        self.forget_in_workspace(workspace, memory_id)

    def forget_in_workspace(self, workspace: str, memory_id: str) -> None:
        """Delete one conclusion from a pool workspace and drop its provenance."""
        try:
            self.honcho.delete_conclusion(workspace, memory_id)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        self.pool_provenance.forget(memory_id)

    def correct(
        self,
        agent_id: UUID,
        memory_id: str,
        payload: MemoryItemUpdate,
        context: CurrentUserContext,
        *,
        observer: str | None = None,
        observed: str | None = None,
    ) -> MemoryItemRead:
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_MANAGE, context)
        workspace = self._require_pool(agent)
        existing = self._require_curate(agent, workspace, memory_id, context, observer=observer, observed=observed)
        return self._apply_correction(workspace, memory_id, existing, payload)

    def correct_in_workspace(self, workspace: str, memory_id: str, payload: MemoryItemUpdate) -> MemoryItemRead:
        """Replace one memory's content in a pool workspace (group-page path,
        already gated on `memory_group.manage`, so it curates any member's memory)."""
        try:
            existing = self._find(workspace, memory_id)
        except HonchoError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
        return self._apply_correction(workspace, memory_id, existing, payload)

    def _apply_correction(
        self, workspace: str, memory_id: str, existing: dict, payload: MemoryItemUpdate
    ) -> MemoryItemRead:
        """Replace `existing`'s content, preserving its peer pair.

        Honcho has no update endpoint, so this deletes and recreates. Two
        consequences are deliberately visible rather than hidden: the item gets a
        new id, and the replacement is always `explicit` because create cannot set
        a level — a corrected deduction stops being labelled a deduction.
        """
        try:
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
        return _to_memory_item(
            created,
            self.pool_provenance.find_for_conclusions([new_id]).get(new_id),
            self._agent_names_in([created]),
        )

    def search_memory(
        self, agent_id: UUID, query: str, context: CurrentUserContext, *, limit: int, scope: str = "pool"
    ) -> list[MemoryItemRead]:
        """Search the Agent's pool memory.

        Same access rule as `list_memory`: `scope="mine"` searches only this
        Agent's own contributions (plain `agent.memory.read`); the whole pool
        (`scope="pool"`) needs `memory_group.manage`, so a single-Agent viewer
        cannot search other members' memory.
        """
        agent = self._require(agent_id, PermissionKey.AGENT_MEMORY_READ, context)
        if scope != "mine":
            self._require_group_manage(agent, context)
        if not memory_active(agent, honcho_enabled=self.config.honcho_enabled):
            return []
        observer = ai_peer_name_for_agent(agent) if scope == "mine" else None
        return self.search_memory_for_workspace(
            memory_workspace_for_agent(agent), query, limit=limit, observer=observer
        )

    def search_memory_for_workspace(
        self, workspace: str, query: str, *, limit: int, observer: str | None = None
    ) -> list[MemoryItemRead]:
        """Semantic search across a pool workspace.

        Honcho searches one (observer, observed) collection at a time — the vectors
        are stored per pair, and it rejects a search that names neither. Facts about
        the person are keyed `observed = the human peer`, so we pin the observed side
        to the pool's human peer(s) and fan out over observers, instead of crossing
        every peer with every peer (which burned most queries on empty or irrelevant
        pairs). `observer` limits it to one member (scope="mine"); None searches
        every member (pool-wide). Complete by default — the whole observer set is
        searched, never a silent first-N slice. The group-size cap keeps the fan-out
        small; the defensive ceiling only trips if that cap is bypassed, and then it
        reports partial results rather than lying. Pairs run concurrently, then
        dedupe, so output is deterministic.
        """
        peers = self.honcho.list_peers(workspace)
        # Facts about the person live under the human peer; fall back to every peer
        # only in the unusual case where a pool has no human peer yet.
        observed_targets = [p for p in peers if p in _HUMAN_PEERS] or peers
        observers = [observer] if observer is not None else peers
        pairs = [(o, d) for o in observers for d in observed_targets]
        if len(pairs) > _MAX_SEARCH_PAIRS:
            logger.warning(
                "Memory search over %s hit the pair ceiling (%d > %d); results are partial. "
                "This should not happen under the group-size cap.",
                workspace,
                len(pairs),
                _MAX_SEARCH_PAIRS,
            )
            pairs = pairs[:_MAX_SEARCH_PAIRS]
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
        top = results[:limit]
        name_by_peer = self._agent_names_in(top)
        return [_to_memory_item(i, name_by_peer=name_by_peer) for i in top]

    def _find(
        self, workspace: str, memory_id: str, *, observer: str | None = None, observed: str | None = None
    ) -> dict | None:
        """Locate one memory so a write can preserve its peer pair.

        Honcho has no get-by-id, so this pages the conclusions. The optional
        `(observer, observed)` — the pair the client already displayed — scopes the
        walk to that one collection instead of scanning the whole pool, so an old
        item in a large pool is still found rather than falling off the page cap.
        """
        return self.honcho.find_conclusion(workspace, memory_id, observer=observer, observed=observed)


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
