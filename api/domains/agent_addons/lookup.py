from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agent_addons.models import ApprovedAddon
from api.domains.agent_addons.repository import AgentAddonRepository


@inject
@singleton
@dataclass
class AgentAddonLookupService:
    """The approved add-ons an Agent starts with, for provisioning and Agent reads.

    No authorization: callers have already authorized the Agent.
    """

    repository: AgentAddonRepository

    def approved(self, agent_id: UUID) -> list[ApprovedAddon]:
        return self.repository.approved_for_agent(agent_id)

    def ever_approved(self, agent_id: UUID) -> bool:
        """Whether any add-on of this Agent was ever approved, so its add-ons volume may exist."""
        return self.repository.ever_approved(agent_id)

    def approved_for_agents(self, agent_ids: list[UUID]) -> Mapping[UUID, list[ApprovedAddon]]:
        return self.repository.approved_for_agents(agent_ids)
