"""Memory-pool workspace derivation.

Agents in the same memory group share one Honcho workspace (`af-pool-<group id>`)
so they see each other's memory, instead of the old one-workspace-per-Agent
isolation. Group membership is the opt-in; an Agent with no group has no shared
memory.
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


def _agent(*, memory_group_id: uuid.UUID | None) -> Agent:
    agent = Mock(spec=Agent)
    agent.memory_group_id = memory_group_id
    return agent


def test_memory_active_requires_infra_and_group_membership():
    """Memory is on only when Honcho is deployed AND the Agent is in a group.
    Leaving the group (memory_group_id None) drops pool access on the next start;
    the Agent's past contributions stay in the pool (this only gates access)."""
    in_group = _agent(memory_group_id=uuid.uuid4())
    no_group = _agent(memory_group_id=None)
    assert_that(memory_active(in_group, honcho_enabled=True), equal_to(True))
    assert_that(memory_active(no_group, honcho_enabled=True), equal_to(False))
    assert_that(memory_active(in_group, honcho_enabled=False), equal_to(False))


def test_pool_id_and_workspace_are_the_group_id():
    group_id = uuid.uuid4()
    agent = _agent(memory_group_id=group_id)
    assert_that(memory_pool_id_for_agent(agent), equal_to(str(group_id)))
    assert_that(memory_workspace_for_agent(agent), equal_to(f"af-pool-{group_id}"))


def test_workspace_id_for_pool_prefixes_pool():
    assert_that(workspace_id_for_pool("org-123"), equal_to("af-pool-org-123"))


def test_pool_id_round_trips_through_workspace_name():
    assert_that(pool_id_from_workspace("af-pool-abc"), equal_to("abc"))


def test_legacy_per_agent_workspace_is_not_a_pool():
    # Old per-Agent workspaces are `af-<uuid>` — not pool workspaces, so the
    # pool parser (used by cost attribution) must not mistake them for one.
    assert_that(pool_id_from_workspace(f"af-{uuid.uuid4()}"), is_(none()))
