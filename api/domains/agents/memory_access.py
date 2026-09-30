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


def new_memory_key(agent_id: UUID) -> str:
    """A fresh key for one Agent, as `<agent id>.<secret>`.

    The runtimes send only a bearer to one base URL, and OpenClaw's SDK drops any
    path on that URL, so the key itself says which Agent is calling. The id only
    selects the row the whole key is then compared against.
    """
    return f"{agent_id}.{secrets.token_urlsafe(32)}"


@inject
@singleton
@dataclass
class AgentMemoryAccessService:
    agents: AgentRepository
    organization_lookup: OrganizationLookupService
    config: Config

    def authorize(self, provided_key: str) -> str:
        """The pool workspace the key's Agent may use, or an exception saying why not."""
        agent_id, _, secret = provided_key.partition(".")
        if not secret:
            raise MemoryKeyRejected
        try:
            agent = self.agents.get_by_id(UUID(agent_id))
        except ValueError:
            raise MemoryKeyRejected from None
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
