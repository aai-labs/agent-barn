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
    memory_endpoint_for_agent,
)
from api.domains.agents.models import AgentStatus
from api.infrastructure.crypto import encrypt_token

ENCRYPTION_KEY = "q2hQ3Xa0p3wJ9o2sQf8JpJwJ6oY4mZKzJ8m4bJq0zV4="
KEY = "memory-key"


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


def agent(*, group=True, status=AgentStatus.RUNNING, key=KEY):
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        memory_group_id=uuid.uuid4() if group else None,
        status=status,
        memory_key_encrypted=encrypt_token(key, ENCRYPTION_KEY) if key else None,
    )


def service(found, *, suspended=False, **config_values):
    agents = MagicMock()
    agents.get_by_id.return_value = found
    lookup = MagicMock()
    lookup.memory_suspended.return_value = suspended
    return AgentMemoryAccessService(agents=agents, organization_lookup=lookup, config=config(**config_values))


def test_a_running_agent_in_a_group_reaches_its_own_pool():
    member = agent()
    workspace = service(member).authorize(member.id, KEY)
    assert_that(workspace, equal_to(f"af-pool-{member.memory_group_id}"))


def test_a_wrong_key_is_rejected():
    member = agent()
    with pytest.raises(MemoryKeyRejected):
        service(member).authorize(member.id, "copied-from-somewhere-else")


@pytest.mark.parametrize("found", [None, agent(key=None)])
def test_an_unknown_agent_or_one_never_issued_a_key_is_rejected(found):
    with pytest.raises(MemoryKeyRejected):
        service(found).authorize(uuid.uuid4(), KEY)


@pytest.mark.parametrize("status", [AgentStatus.STOPPED, AgentStatus.ERROR])
def test_an_agent_that_is_not_running_is_refused_even_with_its_key(status):
    member = agent(status=status)
    with pytest.raises(MemoryAccessDenied):
        service(member).authorize(member.id, KEY)


def test_an_agent_that_left_its_group_is_refused_even_with_its_key():
    member = agent(group=False)
    with pytest.raises(MemoryAccessDenied):
        service(member).authorize(member.id, KEY)


def test_a_suspended_organizations_agent_is_refused():
    member = agent()
    with pytest.raises(MemoryAccessDenied):
        service(member, suspended=True).authorize(member.id, KEY)


def test_memory_is_refused_when_honcho_is_not_deployed():
    member = agent()
    with pytest.raises(MemoryAccessDenied):
        service(member, honcho_enabled=False).authorize(member.id, KEY)


def test_an_agent_reaches_memory_through_its_own_path_on_the_proxy():
    """The runtimes send only a bearer, so the Agent's id travels in the base URL
    they are given; both SDKs append `/v3/...` to it."""
    agent_id = uuid.uuid4()
    endpoint = memory_endpoint_for_agent(config(agent_memory_proxy_base_url="http://memory-proxy:8003/"), agent_id)
    assert_that(endpoint, equal_to(f"http://memory-proxy:8003/agents/{agent_id}"))
