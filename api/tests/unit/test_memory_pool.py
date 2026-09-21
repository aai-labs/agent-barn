"""Memory-pool workspace derivation.

Opted-in Agents share a per-pool Honcho workspace so they can see each other's
memory, instead of the old one-workspace-per-Agent isolation. The default pool
is the org "house pool" (derived from the org id); a named pool id overrides it.
"""

import uuid
from unittest.mock import Mock

from hamcrest import assert_that, equal_to, is_, none

from api.domains.agents.memory_sharing import (
    memory_active,
    memory_pool_id_for_agent,
    memory_workspace_for_agent,
)
from api.domains.agents.models import Agent
from api.infrastructure.honcho.client import (
    pool_id_from_workspace,
    workspace_id_for_pool,
)


def _agent(*, organization_id: uuid.UUID, memory_pool_id: str | None, memory_enabled: bool = True) -> Agent:
    agent = Mock(spec=Agent)
    agent.organization_id = organization_id
    agent.memory_pool_id = memory_pool_id
    agent.memory_enabled = memory_enabled
    return agent


def test_memory_active_requires_both_infra_and_opt_in():
    """Memory is on only when Honcho is deployed AND the Agent has opted in.
    Opting out (memory_enabled false) drops pool access on the next start; the
    Agent's past contributions stay in the pool (this only gates access)."""
    org = uuid.uuid4()
    opted_in = _agent(organization_id=org, memory_pool_id=None, memory_enabled=True)
    opted_out = _agent(organization_id=org, memory_pool_id=None, memory_enabled=False)
    assert_that(memory_active(opted_in, honcho_enabled=True), equal_to(True))
    assert_that(memory_active(opted_out, honcho_enabled=True), equal_to(False))
    assert_that(memory_active(opted_in, honcho_enabled=False), equal_to(False))


def test_workspace_id_for_pool_prefixes_pool():
    assert_that(workspace_id_for_pool("org-123"), equal_to("af-pool-org-123"))


def test_pool_id_round_trips_through_workspace_name():
    assert_that(pool_id_from_workspace("af-pool-abc"), equal_to("abc"))


def test_legacy_per_agent_workspace_is_not_a_pool():
    # Old per-Agent workspaces are `af-<uuid>` — not pool workspaces, so the
    # pool parser (used by cost attribution) must not mistake them for one.
    assert_that(pool_id_from_workspace(f"af-{uuid.uuid4()}"), is_(none()))


def test_house_pool_defaults_to_org():
    org = uuid.uuid4()
    agent = _agent(organization_id=org, memory_pool_id=None)
    assert_that(memory_pool_id_for_agent(agent), equal_to(str(org)))
    assert_that(memory_workspace_for_agent(agent), equal_to(f"af-pool-{org}"))


def test_named_pool_overrides_house_pool():
    org = uuid.uuid4()
    agent = _agent(organization_id=org, memory_pool_id="team-research")
    assert_that(memory_pool_id_for_agent(agent), equal_to("team-research"))
    assert_that(memory_workspace_for_agent(agent), equal_to("af-pool-team-research"))
