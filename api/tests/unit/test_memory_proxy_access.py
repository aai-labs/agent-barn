"""Who the memory proxy lets through, and to which pool (AF-338).

An Agent holds a memory key instead of a Honcho token. The key is checked on every
request against the Agent as it is now — running, still in a group, its
Organization's memory not suspended — so leaving a group, stopping, or running
out of budget cuts a copied key off at once, which Honcho's own tokens cannot.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.agents.memory_access import (
    AgentMemoryAccessService,
    MemoryAccessDenied,
    MemoryKeyRejected,
    new_memory_key,
)
from api.domains.agents.models import AgentStatus
from api.infrastructure.crypto import encrypt_token

ENCRYPTION_KEY = "q2hQ3Xa0p3wJ9o2sQf8JpJwJ6oY4mZKzJ8m4bJq0zV4="


def config(**values):
    return Config.model_validate(
        {
            "db_connection_url": "postgresql://test:test@localhost/test",
            "secret_signing_key": "test",
            "platform_admin_credentials": "test:test",
            "organization_default_llm_budget_usd": 100,
            "agent_default_llm_budget_usd": 10,
            "agent_token_encryption_key": ENCRYPTION_KEY,
            "honcho_enabled": True,
            **values,
        }
    )


def agent(*, group=True, status=AgentStatus.RUNNING, issued=True):
    agent_id = uuid.uuid4()
    key = new_memory_key(agent_id)
    return MagicMock(
        id=agent_id,
        organization_id=uuid.uuid4(),
        memory_group_id=uuid.uuid4() if group else None,
        status=status,
        memory_key_encrypted=encrypt_token(key, ENCRYPTION_KEY) if issued else None,
        key=key,
    )


def service(found, *, suspended=False, **config_values):
    agents = MagicMock()
    agents.get_by_id.return_value = found
    lookup = MagicMock()
    lookup.memory_suspended.return_value = suspended
    return AgentMemoryAccessService(agents=agents, organization_lookup=lookup, config=config(**config_values))


def test_a_running_agent_in_a_group_reaches_its_own_pool():
    member = agent()
    workspace = service(member).authorize(member.key)
    assert_that(workspace, equal_to(f"af-pool-{member.memory_group_id}"))


def test_a_wrong_key_is_rejected():
    member = agent()
    with pytest.raises(MemoryKeyRejected):
        service(member).authorize(f"{member.id}.copied-from-somewhere-else")


@pytest.mark.parametrize("found", [None, agent(issued=False)])
def test_an_unknown_agent_or_one_never_issued_a_key_is_rejected(found):
    with pytest.raises(MemoryKeyRejected):
        service(found).authorize(new_memory_key(uuid.uuid4()))


@pytest.mark.parametrize("key", ["", "no-agent-id", "not-a-uuid.secret", "."])
def test_a_key_that_names_no_agent_is_rejected_without_a_lookup(key):
    found = agent()
    access = service(found)
    with pytest.raises(MemoryKeyRejected):
        access.authorize(key)
    access.agents.get_by_id.assert_not_called()


def test_another_agents_valid_key_does_not_open_this_one():
    """The id in a key only selects the row to check it against."""
    member, other = agent(), agent()
    forged = f"{member.id}.{other.key.split('.', 1)[1]}"
    with pytest.raises(MemoryKeyRejected):
        service(member).authorize(forged)


@pytest.mark.parametrize("status", [AgentStatus.STOPPED, AgentStatus.ERROR])
def test_an_agent_that_is_not_running_is_refused_even_with_its_key(status):
    member = agent(status=status)
    with pytest.raises(MemoryAccessDenied):
        service(member).authorize(member.key)


def test_an_agent_that_left_its_group_is_refused_even_with_its_key():
    member = agent(group=False)
    with pytest.raises(MemoryAccessDenied):
        service(member).authorize(member.key)


def test_a_suspended_organizations_agent_is_refused():
    member = agent()
    with pytest.raises(MemoryAccessDenied):
        service(member, suspended=True).authorize(member.key)


def test_memory_is_refused_when_honcho_is_not_deployed():
    member = agent()
    with pytest.raises(MemoryAccessDenied):
        service(member, honcho_enabled=False).authorize(member.key)


def test_a_key_names_its_agent_so_the_runtime_needs_only_the_proxy_url():
    """The runtimes send only a bearer, and OpenClaw's SDK drops any path on the base
    URL, so the Agent is identified by its key rather than its address."""
    agent_id = uuid.uuid4()
    key = new_memory_key(agent_id)
    assert_that(key.split(".", 1)[0], equal_to(str(agent_id)))
    assert_that(len(key.split(".", 1)[1]) >= 32, equal_to(True))
