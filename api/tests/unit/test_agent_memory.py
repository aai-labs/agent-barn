"""Reading and curating what an Agent has learned.

Memory is stored per (observer, observed) peer pair, so these assert the pair
survives to the caller — collapsing it would misrepresent whose memory it is.
Correction is delete-then-create because Honcho has no update endpoint, and the
consequences of that are pinned here rather than left as a surprise.
"""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to, has_length

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.memory_sharing import AgentMemoryService, MemoryItemUpdate
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import AgentRepository, SharedMemoryFactRepository, SharedMemoryProvenance
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.honcho.client import HonchoClient, HonchoError

AGENT_ID = uuid7()


def _agent() -> Agent:
    agent = Mock(spec=Agent)
    agent.id = AGENT_ID
    agent.name = "watcher"
    return agent


def _service(*, honcho_enabled: bool = True):
    authorization = Mock(spec=AgentAuthorization)
    authorization.require_action.return_value = _agent()
    authorization.require_action_allowing_deleted.return_value = _agent()
    honcho = Mock(spec=HonchoClient)
    provenance = Mock(spec=SharedMemoryFactRepository)
    provenance.find_for_conclusions.return_value = {}
    service = AgentMemoryService(
        agent_authorization=authorization,
        honcho=honcho,
        config=Config(honcho_enabled=honcho_enabled),
        provenance=provenance,
        permission_policy=Mock(spec=PermissionPolicy),
        agent_repository=Mock(spec=AgentRepository),
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


def _org_agent(name: str, *, deleted: bool = False):
    agent = Mock(spec=Agent)
    agent.id = uuid7()
    agent.name = name
    # A plain string, which is what SQLModel returns for this column — the enum
    # member a Mock would otherwise carry hides that the read model has to
    # normalise it.
    agent.agent_type = AgentType.HERMES.value
    agent.deleted_at = datetime.now(UTC) if deleted else None
    return agent


def _org_context():
    context = Mock(spec=CurrentUserContext)
    context.require_current_user_organization.return_value = Mock(organization_id=uuid7())
    return context


def test_organization_directory_includes_deleted_agents():
    """The reason this view exists: a deleted Agent keeps its memory, so without
    listing it here that memory is personal data with no route to it."""
    service, _auth, honcho, _prov = _service()
    service.agent_repository.find_all_for_org.return_value = [
        _org_agent("live-one"),
        _org_agent("gone-one", deleted=True),
    ]
    honcho.list_conclusions.return_value = ([], 7)

    result = service.list_organization_memory(_org_context())

    by_name = {a.agent_name: a for a in result.agents}
    assert_that(by_name["gone-one"].deleted, equal_to(True))
    assert_that(by_name["live-one"].deleted, equal_to(False))
    assert_that(result.total_memories, equal_to(14))


def test_an_unreachable_workspace_is_not_reported_as_empty():
    """Zero means "this Agent learned nothing", which is a different claim from
    "we could not ask". Collapsing them would quietly invite someone to conclude
    an Agent has no memory when its store is simply down."""
    service, _auth, honcho, _prov = _service()
    service.agent_repository.find_all_for_org.return_value = [_org_agent("unreachable")]
    honcho.list_conclusions.side_effect = HonchoError("down")

    result = service.list_organization_memory(_org_context())

    assert_that(result.agents[0].memory_count, equal_to(None))
    assert_that(result.partial, equal_to(True))
    assert_that(result.total_memories, equal_to(0))


def test_one_unreachable_agent_does_not_blank_the_others():
    service, _auth, honcho, _prov = _service()
    service.agent_repository.find_all_for_org.return_value = [_org_agent("a"), _org_agent("b")]
    honcho.list_conclusions.side_effect = [HonchoError("down"), ([], 5)]

    result = service.list_organization_memory(_org_context())

    counts = {a.agent_name: a.memory_count for a in result.agents}
    assert_that(counts, equal_to({"a": None, "b": 5}))
    assert_that(result.total_memories, equal_to(5))


def test_organization_directory_requires_organization_wide_permission():
    """Per-Agent grants are not enough: this lists Agents the caller may hold no
    individual grant on, deleted ones included."""
    service, _auth, honcho, _prov = _service()
    service.agent_repository.find_all_for_org.return_value = []
    service.permission_policy.require_organization.side_effect = HTTPException(status_code=403)

    with pytest.raises(HTTPException):
        service.list_organization_memory(_org_context())

    honcho.list_conclusions.assert_not_called()
