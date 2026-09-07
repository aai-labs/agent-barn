"""Explicit cross-Agent memory sharing.

Nothing crosses a workspace boundary automatically (see the ADR); this is the
one deliberate crossing, so what's tested here is that it stays deliberate:
every destination is authorized on its own merits, a failure on one destination
does not silently swallow another's, and the AI peer each fact is aimed at
matches what the runtime builders actually configured — a mismatch there would
mean the fact lands somewhere the Agent's own reasoning never looks.
"""

from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to, has_length

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.memory_sharing import (
    MemorySharingService,
    SharedFactCreate,
    ai_peer_name_for_agent,
)
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import SharedMemoryFactRepository
from api.domains.auth.models import CurrentUserContext
from api.infrastructure.honcho.client import HonchoClient, HonchoError

ORG_ID = uuid7()


def _agent(agent_type: AgentType, name: str = "watcher") -> Agent:
    agent = Mock(spec=Agent)
    agent.id = uuid7()
    agent.organization_id = ORG_ID
    agent.agent_type = agent_type
    agent.name = name
    return agent


def test_hermes_ai_peer_matches_what_build_honcho_config_sets():
    """Duplicated from `builders/hermes.py::build_honcho_config`'s `aiPeer` field
    by necessity — nothing imports the other's constant, so a rename on either
    side silently breaks sharing until it's tested against a live Agent."""
    agent = _agent(AgentType.HERMES, name="scrum-master")

    assert_that(ai_peer_name_for_agent(agent), equal_to("agent-scrum-master"))


def test_openclaw_ai_peer_is_fixed_regardless_of_agent_name():
    """Every OpenClaw Agent's config names its one logical agent "main"
    (`builders/openclaw.py`), and Honcho's own OpenClaw plugin docs fix the AI
    peer as `agent-{openclaw_agent_id}` — so this is `agent-main` for every
    OpenClaw Agent. Workspace isolation is what separates them, not this name."""
    first = _agent(AgentType.OPENCLAW, name="reviewer")
    second = _agent(AgentType.OPENCLAW, name="a-totally-different-name")

    assert_that(ai_peer_name_for_agent(first), equal_to("agent-main"))
    assert_that(ai_peer_name_for_agent(second), equal_to("agent-main"))


def _service(*, honcho_enabled: bool = True):
    authorization = Mock(spec=AgentAuthorization)
    honcho = Mock(spec=HonchoClient)
    honcho.share_fact.return_value = {"id": "conclusion-1"}
    provenance = Mock(spec=SharedMemoryFactRepository)
    config = Config(honcho_enabled=honcho_enabled)
    service = MemorySharingService(
        agent_authorization=authorization, honcho=honcho, config=config, provenance=provenance
    )
    return service, authorization, honcho, provenance


def _context() -> CurrentUserContext:
    context = Mock(spec=CurrentUserContext)
    # `spec` does not surface pydantic fields, and sharing records who performed it.
    context.user = Mock(id=uuid7())
    return context


def test_rejects_when_honcho_backed_memory_is_not_enabled():
    """Nothing is written anywhere: no Agent has a Honcho workspace to share into,
    so failing fast avoids a confusing Honcho-unreachable error instead."""
    service, authorization, honcho, _provenance = _service(honcho_enabled=False)

    with pytest.raises(HTTPException) as exc:
        service.share_fact(uuid7(), SharedFactCreate(content="fact", targetAgentIds=[uuid7()]), _context())

    assert_that(exc.value.status_code, equal_to(409))
    authorization.require_action.assert_not_called()
    honcho.share_fact.assert_not_called()


def test_shares_into_every_target_with_its_own_ai_peer():
    service, authorization, honcho, _provenance = _service()
    source = _agent(AgentType.HERMES)
    target_a = _agent(AgentType.HERMES, name="agent-a")
    target_b = _agent(AgentType.OPENCLAW, name="agent-b")
    authorization.require_action.side_effect = [source, target_a, target_b]

    result = service.share_fact(
        source.id,
        SharedFactCreate(content="prefers terse updates", targetAgentIds=[target_a.id, target_b.id]),
        _context(),
    )

    assert_that(result.results, has_length(2))
    assert_that(all(r.shared for r in result.results), equal_to(True))
    calls = {c.args[1] for c in honcho.share_fact.call_args_list}
    assert_that(calls, equal_to({"agent-agent-a", "agent-main"}))


def test_one_targets_honcho_failure_does_not_swallow_another_targets_success():
    service, authorization, honcho, _provenance = _service()
    source = _agent(AgentType.HERMES)
    target_a = _agent(AgentType.HERMES, name="agent-a")
    target_b = _agent(AgentType.HERMES, name="agent-b")
    authorization.require_action.side_effect = [source, target_a, target_b]
    honcho.share_fact.side_effect = [HonchoError("unreachable"), {"id": "conclusion-2"}]

    result = service.share_fact(
        source.id,
        SharedFactCreate(content="fact", targetAgentIds=[target_a.id, target_b.id]),
        _context(),
    )

    by_agent = {r.agent_id: r for r in result.results}
    assert_that(by_agent[target_a.id].shared, equal_to(False))
    assert_that(by_agent[target_b.id].shared, equal_to(True))


def test_lacking_permission_on_any_target_fails_the_whole_call():
    """Unlike a Honcho-side failure, an authorization failure on one target
    aborts before any writes happen — silently returning per-target results here
    would let a caller learn whether an Agent they cannot see exists."""
    service, authorization, _, _provenance = _service()
    source = _agent(AgentType.HERMES)
    authorization.require_action.side_effect = [source, HTTPException(status_code=403)]

    with pytest.raises(HTTPException):
        service.share_fact(source.id, SharedFactCreate(content="fact", targetAgentIds=[uuid7()]), _context())


def test_sharing_into_a_destination_uses_the_memory_permission():
    """Writing into another Agent's memory is the same power as editing it directly,
    so it takes agent.memory.manage rather than the broader agent.update."""
    from api.domains.rbac.catalog import PermissionKey

    service, authorization, _, _provenance = _service()
    source = _agent(AgentType.HERMES)
    target = _agent(AgentType.HERMES, name="target")
    authorization.require_action.side_effect = [source, target]

    service.share_fact(source.id, SharedFactCreate(content="fact", targetAgentIds=[target.id]), _context())

    used = [c.args[2] for c in authorization.require_action.call_args_list]
    assert_that(used, equal_to([PermissionKey.AGENT_READ, PermissionKey.AGENT_MEMORY_MANAGE]))


def test_shared_fact_is_written_to_the_destination_agents_own_self_model():
    """A message from a synthetic peer is stored and reasoned over by Honcho but is
    never surfaced by the runtime's own recall — verified against a live Agent. A
    conclusion on the Agent's self-model is where recall actually looks, so both
    sides of the peer pair are the destination's AI peer."""
    service, authorization, honcho, _provenance = _service()
    source = _agent(AgentType.HERMES)
    target = _agent(AgentType.HERMES, name="scribe")
    authorization.require_action.side_effect = [source, target]

    service.share_fact(
        source.id, SharedFactCreate(content="deploys are Tuesdays", targetAgentIds=[target.id]), _context()
    )

    args = honcho.share_fact.call_args.args
    assert_that(args[1], equal_to("agent-scribe"))
    assert_that(args[2], equal_to("deploys are Tuesdays"))


def test_sharing_records_which_agent_a_fact_came_from():
    """Honcho stores no metadata on a conclusion, so once written a shared fact is
    indistinguishable from one the Agent worked out itself. Without this row the
    memory view labels it "(about itself)" — true of where it is stored, a lie
    about where it came from."""
    service, authorization, honcho, provenance = _service()
    source = _agent(AgentType.HERMES, name="scout")
    target = _agent(AgentType.HERMES, name="receiver")
    authorization.require_action.side_effect = [source, target]
    honcho.share_fact.return_value = {"id": "conclusion-xyz"}

    service.share_fact(source.id, SharedFactCreate(content="fact", targetAgentIds=[target.id]), _context())

    provenance.record.assert_called_once()
    recorded = provenance.record.call_args.kwargs
    assert_that(recorded["conclusion_id"], equal_to("conclusion-xyz"))
    assert_that(recorded["target_agent_id"], equal_to(target.id))
    assert_that(recorded["source_agent_id"], equal_to(source.id))


def test_a_share_that_honcho_rejected_records_no_provenance():
    """A provenance row for a conclusion that was never created would badge some
    unrelated future memory as shared, since Honcho ids are not ours to predict."""
    service, authorization, honcho, provenance = _service()
    source = _agent(AgentType.HERMES)
    target = _agent(AgentType.HERMES, name="receiver")
    authorization.require_action.side_effect = [source, target]
    honcho.share_fact.side_effect = HonchoError("unreachable")

    service.share_fact(source.id, SharedFactCreate(content="fact", targetAgentIds=[target.id]), _context())

    provenance.record.assert_not_called()
