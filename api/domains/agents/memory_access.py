"""Who the memory proxy lets through, and to which pool (AF-338).

Honcho's tokens cannot be revoked, so an Agent never holds one. It holds a memory
key instead, checked here on every request against the Agent as it is now: a key
that was copied stops working the moment its Agent stops, leaves its group, or its
Organization's memory is suspended.
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.memory_sharing import memory_active, memory_workspace_for_agent
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.organizations.lookup import OrganizationLookupService
from api.infrastructure.crypto import decrypt_token


class MemoryKeyRejected(Exception):
    """The caller is not a known Agent holding its current key."""


class MemoryAccessDenied(Exception):
    """A genuine Agent whose memory is off right now."""


def memory_endpoint_for_agent(config: Config, agent_id: UUID) -> str:
    """The base URL an Agent's runtime is given for memory. The runtimes send only a
    bearer, so the Agent's id travels in the path; both SDKs append `/v3/...`."""
    return f"{config.agent_memory_proxy_base_url.rstrip('/')}/agents/{agent_id}"


@inject
@singleton
@dataclass
class AgentMemoryAccessService:
    agents: AgentRepository
    organization_lookup: OrganizationLookupService
    config: Config

    def authorize(self, agent_id: UUID, provided_key: str) -> str:
        """The pool workspace this Agent may use, or an exception saying why not."""
        agent = self.agents.get_by_id(agent_id)
        if agent is None or not agent.memory_key_encrypted:
            raise MemoryKeyRejected
        stored = decrypt_token(agent.memory_key_encrypted, self.config.agent_token_encryption_key)
        if not secrets.compare_digest(stored, provided_key):
            raise MemoryKeyRejected
        if agent.status != AgentStatus.RUNNING:
            raise MemoryAccessDenied
        if not memory_active(
            agent,
            honcho_enabled=self.config.honcho_enabled,
            organization_memory_suspended=self.organization_lookup.memory_suspended(agent.organization_id),
        ):
            raise MemoryAccessDenied
        return memory_workspace_for_agent(agent)
