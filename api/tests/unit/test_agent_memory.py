"""Reading and curating what an Agent has learned.

Memory is stored per (observer, observed) peer pair, so these assert the pair
survives to the caller — collapsing it would misrepresent whose memory it is.
Correction is delete-then-create because Honcho has no update endpoint, and the
consequences of that are pinned here rather than left as a surprise.
"""

from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to, has_length

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.memory_sharing import AgentMemoryService, MemoryItemUpdate
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import SharedMemoryFactRepository, SharedMemoryProvenance
from api.domains.auth.models import CurrentUserContext
from api.infrastructure.honcho.client import HonchoClient, HonchoError

AGENT_ID = uuid7()


def _agent() -> Agent:
    agent = Mock(spec=Agent)
    agent.id = AGENT_ID
    agent.name = "watcher"
    agent.agent_type = AgentType.HERMES
    return agent


def _service(*, honcho_enabled: bool = True):
    authorization = Mock(spec=AgentAuthorization)
    authorization.require_action.return_value = _agent()
    authorization.require_action_allowing_deleted.return_value = _agent()
    honcho = Mock(spec=HonchoClient)
    # No peers by default, so the facet pass is a no-op unless a test sets it.
    honcho.list_peers.return_value = []
    provenance = Mock(spec=SharedMemoryFactRepository)
    provenance.find_for_conclusions.return_value = {}
    service = AgentMemoryService(
        agent_authorization=authorization,
        honcho=honcho,
        config=Config(honcho_enabled=honcho_enabled),
        provenance=provenance,
    )
    return service, authorization, honcho, provenance


def _context() -> CurrentUserContext:
    return Mock(spec=CurrentUserContext)


def test_lists_memory_with_the_peer_pair_intact():
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = (
        [
            {
                "id": "c1",
                "content": "owner prefers Rust",
                "observer_id": "agent-main",
                "observed_id": "owner",
                "level": "deductive",
                "created_at": "2026-09-03T20:00:00Z",
            }
        ],
        1,
    )

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(page.items, has_length(1))
    assert_that(page.items[0].observer, equal_to("agent-main"))
    assert_that(page.items[0].observed, equal_to("owner"))
    assert_that(page.items[0].level, equal_to("deductive"))


def test_an_agent_that_has_never_conversed_reads_as_empty_not_an_error():
    """The workspace is created on first conversation, so a new Agent has none."""
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = ([], 0)

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(page.items, equal_to([]))
    assert_that(page.total, equal_to(0))


def test_memory_uses_its_own_permissions_not_general_agent_ones():
    """Memory holds derived conclusions about real people, and rewriting it changes
    what an Agent believes rather than how it is configured — so it is split from
    agent.read/agent.update, the same way secrets were."""
    from api.domains.rbac.catalog import PermissionKey

    service, authorization, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = ([], 0)

    service.list_memory(AGENT_ID, _context(), page=1, size=50)
    assert_that(
        authorization.require_action_allowing_deleted.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_READ)
    )

    service.forget(AGENT_ID, "c1", _context())
    assert_that(
        authorization.require_action_allowing_deleted.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_MANAGE)
    )


def test_correction_preserves_the_peer_pair_of_what_it_replaces():
    """A correction is delete-then-create; recreating it against the wrong pair
    would move the memory to a different person."""
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = (
        [{"id": "c1", "content": "old", "observer_id": "agent-main", "observed_id": "alice", "level": "deductive"}],
        1,
    )
    honcho.create_conclusion.return_value = {
        "id": "c2",
        "content": "new",
        "observer_id": "agent-main",
        "observed_id": "alice",
        "level": "explicit",
    }

    result = service.correct(AGENT_ID, "c1", MemoryItemUpdate(content="new"), _context())

    honcho.delete_conclusion.assert_called_once()
    assert_that(honcho.create_conclusion.call_args.kwargs["observed"], equal_to("alice"))
    # Honcho's create cannot set a level, so a corrected deduction becomes explicit.
    assert_that(result.level, equal_to("explicit"))
    assert_that(result.id, equal_to("c2"))


def test_correcting_something_that_does_not_exist_is_a_404_not_a_silent_create():
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = ([], 0)

    with pytest.raises(HTTPException) as exc:
        service.correct(AGENT_ID, "missing", MemoryItemUpdate(content="new"), _context())

    assert_that(exc.value.status_code, equal_to(404))
    honcho.delete_conclusion.assert_not_called()


def test_honcho_being_unreachable_surfaces_as_bad_gateway_not_a_500():
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.side_effect = HonchoError("connection refused")

    with pytest.raises(HTTPException) as exc:
        service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(502))


def test_memory_is_unavailable_when_honcho_is_disabled():
    service, authorization, _, _provenance = _service(honcho_enabled=False)

    with pytest.raises(HTTPException) as exc:
        service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(409))
    authorization.require_action.assert_not_called()


def test_search_fans_out_across_peer_pairs_and_deduplicates():
    """Honcho searches one (observer, observed) collection at a time — the vectors
    are stored per pair — so an Agent-wide search must fan out and merge. The same
    conclusion can come back from more than one pair query."""
    service, _, honcho, _provenance = _service()
    honcho.list_peers.return_value = ["agent-main", "owner"]
    honcho.search_conclusions.return_value = [
        {"id": "dup", "content": "owner likes Rust", "observer_id": "agent-main", "observed_id": "owner"}
    ]

    results = service.search_memory(AGENT_ID, "languages", _context(), limit=10)

    assert_that(honcho.search_conclusions.call_count, equal_to(4))  # 2 peers squared
    assert_that(results, has_length(1))
    assert_that(results[0].content, equal_to("owner likes Rust"))


def test_search_bounds_the_fan_out():
    """Peers grow with the number of people an Agent talks to, and the fan-out is
    quadratic — unbounded, a search box becomes a slow query over every pair."""
    service, _, honcho, _provenance = _service()
    honcho.list_peers.return_value = [f"peer-{i}" for i in range(40)]
    honcho.search_conclusions.return_value = []

    service.search_memory(AGENT_ID, "anything", _context(), limit=10)

    assert_that(honcho.search_conclusions.call_count, equal_to(64))  # capped at 8 peers


def test_search_needs_only_memory_read_access():
    from api.domains.rbac.catalog import PermissionKey

    service, authorization, honcho, _provenance = _service()
    honcho.list_peers.return_value = []

    service.search_memory(AGENT_ID, "q", _context(), limit=10)

    assert_that(
        authorization.require_action_allowing_deleted.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_READ)
    )


def test_a_deleted_agents_memory_is_still_reachable():
    """Deleting an Agent retains its Honcho workspace, so its memory must remain
    viewable and erasable — otherwise retention leaves personal data that nobody
    can see, search, or delete through the product."""
    service, authorization, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = ([], 0)

    service.list_memory(AGENT_ID, _context(), page=1, size=50)

    # The deleted-tolerant seam is used, not the active-only one.
    authorization.require_action_allowing_deleted.assert_called_once()
    authorization.require_action.assert_not_called()


def test_a_shared_in_memory_is_labelled_with_the_agent_it_came_from():
    """It lands on the destination's own self-model, so without provenance the
    view calls it "(about itself)" — presenting a fact the Agent was handed as one
    it reasoned its way to."""
    service, _authorization, honcho, provenance = _service()
    honcho.list_conclusions.return_value = ([{"id": "c1", "content": "x", "observer_id": "a", "observed_id": "a"}], 1)
    provenance.find_for_conclusions.return_value = {
        "c1": SharedMemoryProvenance(source_agent_id=uuid7(), source_agent_name="scout", shared_at=None)
    }

    page = service.list_memory(uuid7(), _context(), page=1, size=50)

    assert_that(page.items[0].shared_from, equal_to("scout"))


def test_forgetting_a_shared_memory_drops_its_provenance_row():
    """Honcho ids are not reused, but a row pointing at a deleted conclusion is
    dead weight that outlives every Agent that could explain it."""
    service, _authorization, _honcho, provenance = _service()

    service.forget(uuid7(), "c1", _context())

    provenance.forget.assert_called_once_with("c1")


def test_correcting_a_shared_memory_keeps_it_marked_as_shared():
    """A correction is a delete plus a create, so the item gets a new Honcho id.
    Editing the wording of a shared fact does not make it self-derived, so the
    provenance has to follow the new id or the badge silently disappears."""
    service, _authorization, honcho, provenance = _service()
    honcho.list_conclusions.return_value = (
        [{"id": "old", "content": "x", "observer_id": "a", "observed_id": "b"}],
        1,
    )
    honcho.create_conclusion.return_value = {"id": "new", "content": "y", "observer_id": "a", "observed_id": "b"}

    service.correct(uuid7(), "old", MemoryItemUpdate(content="y"), _context())

    provenance.carry_forward.assert_called_once_with("old", "new")


def test_facets_count_each_peer_and_put_the_self_model_first():
    """The tab filters by peer, so each facet needs its real count — Honcho counts
    server-side per peer. The Agent's model of itself sorts first, then people by
    how much the Agent knows about them, so the default order leads with the
    fullest buckets."""
    service, _, honcho, _provenance = _service()
    honcho.list_peers.return_value = ["agent-watcher", "owner", "U123"]
    # page fetch, then one count call per peer
    honcho.list_conclusions.side_effect = [
        ([], 0),  # the page itself (unfiltered)
        ([], 65),  # observed=agent-watcher (self)
        ([], 120),  # observed=owner
        ([], 3),  # observed=U123
    ]

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    labels = [(f.label, f.count, f.is_self) for f in page.facets]
    assert_that(labels[0], equal_to(("What watcher knows", 65, True)))
    assert_that(labels[1], equal_to(("About you", 120, False)))
    assert_that(labels[2], equal_to(("About U123", 3, False)))


def test_a_peer_the_agent_never_concluded_about_gets_no_facet():
    """A peer can exist from a single inbound message that produced nothing. A zero
    facet would be a filter that leads to an empty list."""
    service, _, honcho, _provenance = _service()
    honcho.list_peers.return_value = ["agent-watcher", "ghost"]
    honcho.list_conclusions.side_effect = [([], 0), ([], 10), ([], 0)]

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that([f.peer for f in page.facets], equal_to(["agent-watcher"]))


def test_filtering_to_a_peer_scopes_the_query_and_skips_facets():
    """Under a filter the facets are redundant — they describe the whole workspace,
    which the unfiltered view already provided — so they are not recomputed, and
    the query is scoped to that peer as observed."""
    service, _, honcho, _provenance = _service()
    honcho.list_conclusions.return_value = ([], 0)

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50, observed="owner")

    assert_that(page.facets, equal_to([]))
    honcho.list_peers.assert_not_called()
    assert_that(honcho.list_conclusions.call_args.kwargs["observed"], equal_to("owner"))
    # Always scoped to the Agent as observer, filtered or not.
    assert_that(honcho.list_conclusions.call_args.kwargs["observer"], equal_to("agent-watcher"))
