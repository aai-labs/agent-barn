"""Memory-pool workspace derivation.

Opted-in Agents share a per-pool Honcho workspace so they can see each other's
memory, instead of the old one-workspace-per-Agent isolation. The default pool
is the org "house pool" (derived from the org id); a named pool id overrides it.
"""

import uuid
from unittest.mock import Mock

from hamcrest import assert_that, equal_to, is_, none

from api.domains.agents.memory_sharing import (
    memory_pool_id_for_agent,
    memory_workspace_for_agent,
)
from api.domains.agents.models import Agent
from api.infrastructure.honcho.client import (
    pool_id_from_workspace,
    workspace_id_for_pool,
)


def _agent(*, organization_id: uuid.UUID, memory_pool_id: str | None) -> Agent:
    agent = Mock(spec=Agent)
    agent.organization_id = organization_id
    agent.memory_pool_id = memory_pool_id
    return agent


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
