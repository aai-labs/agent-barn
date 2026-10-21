from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agent_sizes.models import AgentSize
from api.domains.agent_sizes.repository import AgentSizeRepository


class MissingDefaultAgentSize(RuntimeError):
    """The catalog has no default size. The migration that created it seeds one, and the
    default can be neither disabled nor deleted, so this means the data was changed by hand."""


@inject
@singleton
@dataclass
class AgentSizeLookupService:
    """Read-only size resolution for other domains, chiefly provisioning.

    Imports nothing but the repository, so AgentService can inject it without an import
    cycle. Mirrors AgentSettingsLookupService.
    """

    repository: AgentSizeRepository

    def resolve(self, agent_size_id: UUID | None = None) -> AgentSize:
        """The size an Agent starts on: the one given, or the catalog's default.

        Every Agent is on the default until Agents can be given a size of their own (Agent
        Sizes PR 2); the values are read at each start, so editing a size reaches an Agent
        the next time it starts.
        """
        if agent_size_id is not None:
            size = self.repository.get(agent_size_id)
            if size is not None:
                return size
        default = self.repository.get_default()
        if default is None:
            raise MissingDefaultAgentSize("The Agent Size catalog has no default size")
        return default
