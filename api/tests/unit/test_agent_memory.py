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
from api.domains.agents.repository import AgentRepository, PoolMemoryProvenance, SharedPoolMemoryFactRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import HonchoClient, HonchoError

AGENT_ID = uuid7()
ORG_ID = uuid7()


def _agent() -> Agent:
    agent = Mock(spec=Agent)
    agent.id = AGENT_ID
    agent.name = "watcher"
    agent.agent_type = AgentType.HERMES
    agent.organization_id = ORG_ID
    # In a group, so it has shared memory (memory_active is true).
    agent.memory_group_id = AGENT_ID
    return agent


def _service(*, honcho_enabled: bool = True):
    authorization = Mock(spec=AgentAuthorization)
    authorization.require_action.return_value = _agent()
    authorization.require_action_allowing_deleted.return_value = _agent()
    honcho = Mock(spec=HonchoClient)
    # No peers by default, so the facet pass is a no-op unless a test sets it.
    honcho.list_peers.return_value = []
    pool_provenance = Mock(spec=SharedPoolMemoryFactRepository)
    pool_provenance.find_for_conclusions.return_value = {}
    agents = Mock(spec=AgentRepository)
    # No agent-peer names resolve unless a test says so; `in` on a bare Mock throws.
    agents.names_by_ids.return_value = {}
    # Manager check is a no-op by default; a test sets side_effect to deny it.
    permission_policy = Mock(spec=PermissionPolicy)
    permission_policy.require_organization.return_value = None
    service = AgentMemoryService(
        agent_authorization=authorization,
        honcho=honcho,
        config=Config(honcho_enabled=honcho_enabled),
        pool_provenance=pool_provenance,
        agents=agents,
        permission_policy=permission_policy,
    )
    # permission_policy is reachable as service.permission_policy where a test needs it.
    return service, authorization, honcho, pool_provenance


def _context() -> CurrentUserContext:
    return Mock(spec=CurrentUserContext)


def test_lists_memory_with_the_peer_pair_intact():
    service, _, honcho, _pool_prov = _service()
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
    service, _, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(page.items, equal_to([]))
    assert_that(page.total, equal_to(0))


def test_memory_uses_its_own_permissions_not_general_agent_ones():
    """Memory holds derived conclusions about real people, and rewriting it changes
    what an Agent believes rather than how it is configured — so it is split from
    agent.read/agent.update, the same way secrets were."""
    from api.domains.rbac.catalog import PermissionKey

    service, authorization, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)
    honcho.find_conclusion.return_value = {"id": "c1", "observer_id": "agent-x", "observed_id": "owner"}

    service.list_memory(AGENT_ID, _context(), page=1, size=50)
    assert_that(authorization.require_action.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_READ))

    service.forget(AGENT_ID, "c1", _context())
    assert_that(authorization.require_action.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_MANAGE))


def test_correction_preserves_the_peer_pair_of_what_it_replaces():
    """A correction is delete-then-create; recreating it against the wrong pair
    would move the memory to a different person."""
    service, _, honcho, _pool_prov = _service()
    honcho.find_conclusion.return_value = {
        "id": "c1",
        "content": "old",
        "observer_id": "agent-main",
        "observed_id": "alice",
        "level": "deductive",
    }
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
    service, _, honcho, _pool_prov = _service()
    honcho.find_conclusion.return_value = None

    with pytest.raises(HTTPException) as exc:
        service.correct(AGENT_ID, "missing", MemoryItemUpdate(content="new"), _context())

    assert_that(exc.value.status_code, equal_to(404))
    honcho.delete_conclusion.assert_not_called()


def test_honcho_being_unreachable_surfaces_as_bad_gateway_not_a_500():
    service, _, honcho, _pool_prov = _service()
    honcho.list_conclusions.side_effect = HonchoError("connection refused")

    with pytest.raises(HTTPException) as exc:
        service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(502))


def test_memory_is_unavailable_when_honcho_is_disabled():
    service, authorization, _, _pool_prov = _service(honcho_enabled=False)

    with pytest.raises(HTTPException) as exc:
        service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(exc.value.status_code, equal_to(409))
    authorization.require_action.assert_not_called()


def test_search_pins_observed_to_the_human_and_dedupes():
    """Facts about the person are keyed observed=the human peer, so search pins the
    observed side there and fans out over observers — not every peer × every peer.
    With two peers that is (agent, owner) and (owner, owner): 2 queries, not 4. The
    same conclusion coming back from more than one pair is deduped."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = ["agent-main", "owner"]
    honcho.search_conclusions.return_value = [
        {"id": "dup", "content": "owner likes Rust", "observer_id": "agent-main", "observed_id": "owner"}
    ]

    results = service.search_memory(AGENT_ID, "languages", _context(), limit=10)

    assert_that(honcho.search_conclusions.call_count, equal_to(2))
    # Every query pins observed to the human peer.
    assert all(call.kwargs["observed"] == "owner" for call in honcho.search_conclusions.call_args_list)
    assert_that(results, has_length(1))
    assert_that(results[0].content, equal_to("owner likes Rust"))


def test_search_is_complete_over_all_observers_no_silent_cap():
    """The old code sliced the first 8 peers and silently dropped the rest, so a
    pool's search could miss a member's memory with no signal. Now search covers
    every observer against the human peer — linear in pool size, complete."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = [f"agent-{i}" for i in range(30)] + ["owner"]
    honcho.search_conclusions.return_value = []

    service.search_memory(AGENT_ID, "anything", _context(), limit=10)

    # 31 observers × 1 human observed = 31 — every member searched, none dropped.
    assert_that(honcho.search_conclusions.call_count, equal_to(31))


def test_pool_scope_requires_group_manage_but_mine_does_not():
    """Pool-wide view is manager-only; scope=mine is fine with plain read."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)
    service.permission_policy.require_organization.side_effect = HTTPException(status_code=403)

    with pytest.raises(HTTPException) as exc:
        service.list_memory(AGENT_ID, _context(), page=1, size=50)  # default scope=pool
    assert_that(exc.value.status_code, equal_to(403))

    service.permission_policy.require_organization.reset_mock(side_effect=True)
    service.list_memory(AGENT_ID, _context(), page=1, size=50, scope="mine")
    service.permission_policy.require_organization.assert_not_called()


def test_curating_another_agents_memory_requires_group_manage():
    """A plain agent.memory.manage holder may curate only this Agent's own
    contributions; forgetting a fact a DIFFERENT agent observed needs manage."""
    service, _, honcho, _pool_prov = _service()
    honcho.find_conclusion.return_value = {"id": "c1", "observer_id": "agent-other", "observed_id": "owner"}
    service.permission_policy.require_organization.side_effect = HTTPException(status_code=403)

    with pytest.raises(HTTPException) as exc:
        service.forget(AGENT_ID, "c1", _context())

    assert_that(exc.value.status_code, equal_to(403))
    honcho.delete_conclusion.assert_not_called()


def test_curating_this_agents_own_memory_needs_no_group_manage():
    service, _, honcho, _pool_prov = _service()
    honcho.find_conclusion.return_value = {"id": "c1", "observer_id": f"agent-{AGENT_ID}", "observed_id": "owner"}
    # Would raise if the manager check were consulted for an own-contribution edit.
    service.permission_policy.require_organization.side_effect = HTTPException(status_code=403)

    service.forget(AGENT_ID, "c1", _context())

    service.permission_policy.require_organization.assert_not_called()
    honcho.delete_conclusion.assert_called_once()


def test_curate_authorizes_on_the_stored_observer_not_a_client_hint():
    """The client-supplied observer only scopes the lookup; authorization uses the
    stored conclusion's real observer, so a forged hint cannot bypass manage."""
    service, _, honcho, _pool_prov = _service()
    honcho.find_conclusion.return_value = {"id": "c1", "observer_id": "agent-other", "observed_id": "owner"}
    service.permission_policy.require_organization.side_effect = HTTPException(status_code=403)

    with pytest.raises(HTTPException):
        # Hint claims it's this agent's own; the stored observer says otherwise.
        service.forget(AGENT_ID, "c1", _context(), observer=f"agent-{AGENT_ID}", observed="owner")


def test_search_mine_scope_limits_to_this_agent():
    """scope="mine" searches only this Agent's own contributions: one pair,
    (this agent, human)."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = [f"agent-{AGENT_ID}", "agent-other", "owner"]
    honcho.search_conclusions.return_value = []

    service.search_memory(AGENT_ID, "anything", _context(), limit=10, scope="mine")

    assert_that(honcho.search_conclusions.call_count, equal_to(1))
    only = honcho.search_conclusions.call_args
    assert_that(only.kwargs["observer"], equal_to(f"agent-{AGENT_ID}"))
    assert_that(only.kwargs["observed"], equal_to("owner"))


def test_search_needs_only_memory_read_access():
    from api.domains.rbac.catalog import PermissionKey

    service, authorization, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = []

    service.search_memory(AGENT_ID, "q", _context(), limit=10)

    assert_that(authorization.require_action.call_args.args[2], equal_to(PermissionKey.AGENT_MEMORY_READ))


def test_agent_memory_uses_the_active_only_authorization_seam():
    """A shared pool's memory is reachable through the group memory page (gated on
    memory_group.manage), so the per-Agent tab no longer needs the deleted-tolerant
    seam — a deleted Agent's contributions live on in the pool, viewed via the group."""
    service, authorization, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)

    service.list_memory(AGENT_ID, _context(), page=1, size=50)

    authorization.require_action.assert_called_once()
    authorization.require_action_allowing_deleted.assert_not_called()


def test_a_memory_shared_in_from_another_pool_carries_its_source_group_id():
    """A cross-pool share lands as an ordinary pooled conclusion, so without the
    pool provenance the view cannot say it came from another group. The id, not a
    name, is returned — the client resolves the name from its groups list."""
    service, _authorization, honcho, pool_prov = _service()
    honcho.list_conclusions.return_value = (
        [{"id": "c1", "content": "x", "observer_id": "owner", "observed_id": "owner"}],
        1,
    )
    source_group = uuid7()
    pool_prov.find_for_conclusions.return_value = {
        "c1": PoolMemoryProvenance(source_group_id=source_group, shared_at=None)
    }

    page = service.list_memory(uuid7(), _context(), page=1, size=50)

    assert_that(page.items[0].shared_from_group_id, equal_to(source_group))


def test_forgetting_a_memory_also_drops_its_pool_provenance():
    service, _authorization, _honcho, pool_prov = _service()

    service.forget(uuid7(), "c1", _context())

    pool_prov.forget.assert_called_once_with("c1")


def test_correcting_a_pool_shared_memory_carries_its_pool_provenance_forward():
    service, _authorization, honcho, pool_prov = _service()
    honcho.find_conclusion.return_value = {"id": "old", "content": "x", "observer_id": "owner", "observed_id": "owner"}
    honcho.create_conclusion.return_value = {
        "id": "new",
        "content": "y",
        "observer_id": "owner",
        "observed_id": "owner",
    }

    service.correct(uuid7(), "old", MemoryItemUpdate(content="y"), _context())

    pool_prov.carry_forward.assert_called_once_with("old", "new")


def test_facets_count_each_peer_and_put_the_self_model_first():
    """The tab filters by peer, so each facet needs its real count — Honcho counts
    server-side per peer. The Agent's model of itself sorts first, then people by
    how much the Agent knows about them, so the default order leads with the
    fullest buckets."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = [f"agent-{AGENT_ID}", "owner", "U123"]
    # page fetch, then one count call per peer
    honcho.list_conclusions.side_effect = [
        ([], 0),  # the page itself (unfiltered)
        ([], 65),  # observed=agent-<id> (self)
        ([], 120),  # observed=owner
        ([], 3),  # observed=U123
    ]

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    labels = [(f.label, f.count, f.is_self) for f in page.facets]
    assert_that(labels[0], equal_to(("What watcher knows", 65, True)))
    assert_that(labels[1], equal_to(("About you", 120, False)))
    assert_that(labels[2], equal_to(("About U123", 3, False)))


def test_another_agents_peer_is_labelled_by_name_not_its_raw_id():
    """A shared pool holds an `agent-<id>` peer per member. The tab must show that
    agent's name, never the raw uuid peer — resolved in one batch from the id."""
    other_id = uuid7()
    service, _, honcho, _pool_prov = _service()
    service.agents.names_by_ids.return_value = {other_id: "Helper"}
    honcho.list_peers.return_value = [f"agent-{AGENT_ID}", "owner", f"agent-{other_id}"]
    honcho.list_conclusions.side_effect = [
        ([], 0),  # the page itself (unfiltered)
        ([], 65),  # observed=agent-<self>
        ([], 120),  # observed=owner
        ([], 3),  # observed=agent-<other>
    ]

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    by_peer = {f.peer: f for f in page.facets}
    assert_that(by_peer[f"agent-{AGENT_ID}"].name, equal_to("watcher"))
    assert_that(by_peer["owner"].name, equal_to("you"))
    assert_that(by_peer[f"agent-{other_id}"].label, equal_to("About Helper"))
    assert_that(by_peer[f"agent-{other_id}"].name, equal_to("Helper"))
    # Name resolution is scoped to the caller's org, so a leaked id can't resolve
    # another org's Agent name.
    assert_that(service.agents.names_by_ids.call_args.args[1], equal_to(ORG_ID))


def test_an_agent_id_baked_into_the_memory_text_is_replaced_with_the_agent_name():
    """Recall answers and shared facts sometimes carry a raw `agent-<uuid>` inside
    the conclusion text itself. The list must show the agent's name there too, not
    just in the surrounding labels."""
    other_id = uuid7()
    service, _, honcho, _pool_prov = _service()
    service.agents.names_by_ids.return_value = {other_id: "Helper"}
    honcho.list_conclusions.return_value = (
        [
            {
                "id": "c1",
                "content": f"agent-{other_id} knows that owner is a fan of oranges",
                "observer_id": f"agent-{other_id}",
                "observed_id": "owner",
            }
        ],
        1,
    )

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that(page.items[0].content, equal_to("Helper knows that owner is a fan of oranges"))


def test_a_peer_the_agent_never_concluded_about_gets_no_facet():
    """A peer can exist from a single inbound message that produced nothing. A zero
    facet would be a filter that leads to an empty list."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_peers.return_value = [f"agent-{AGENT_ID}", "ghost"]
    honcho.list_conclusions.side_effect = [([], 0), ([], 10), ([], 0)]

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50)

    assert_that([f.peer for f in page.facets], equal_to([f"agent-{AGENT_ID}"]))


def test_filtering_to_a_peer_scopes_the_query_and_skips_facets():
    """Under a filter the facets are redundant — they describe the whole workspace,
    which the unfiltered view already provided — so they are not recomputed, and
    the query is scoped to that peer as observed."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)

    page = service.list_memory(AGENT_ID, _context(), page=1, size=50, observed="owner")

    assert_that(page.facets, equal_to([]))
    honcho.list_peers.assert_not_called()
    assert_that(honcho.list_conclusions.call_args.kwargs["observed"], equal_to("owner"))
    # Default scope is the whole pool, so observer is left open (every member's
    # conclusions), not pinned to this Agent.
    assert_that(honcho.list_conclusions.call_args.kwargs["observer"], equal_to(None))


def test_mine_scope_pins_the_query_to_this_agent():
    """scope="mine" narrows the pool view to what THIS Agent concluded — its own
    peer as observer."""
    service, _, honcho, _pool_prov = _service()
    honcho.list_conclusions.return_value = ([], 0)

    service.list_memory(AGENT_ID, _context(), page=1, size=50, observed="owner", scope="mine")

    # Peer identity is the stable agent id (not the name), so a rename never
    # orphans memory and Honcho never renormalizes the peer.
    assert_that(honcho.list_conclusions.call_args.kwargs["observer"], equal_to(f"agent-{AGENT_ID}"))
