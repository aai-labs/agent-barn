from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agent_sizes.models import AgentSize, AgentSizeOption
from api.domains.agent_sizes.repository import AgentSizeRepository


class MissingDefaultAgentSize(RuntimeError):
    """The catalog has no default size. The migration that created it seeds one, and the
    default can be neither disabled nor deleted, so this means the data was changed by hand."""


@dataclass(frozen=True)
class AgentSizeCatalog:
    """Every size at one moment, so a list of Agents resolves theirs without a query each."""

    sizes: dict[UUID, AgentSize]
    default: AgentSize

    def resolve(self, agent_size_id: UUID | None) -> AgentSize:
        if agent_size_id is not None and agent_size_id in self.sizes:
            return self.sizes[agent_size_id]
        return self.default


@inject
@singleton
@dataclass
class AgentSizeLookupService:
    """Read-only size resolution for other domains, chiefly provisioning and Agent reads.

    Imports nothing but the repository, so AgentService can inject it without an import
    cycle. Mirrors AgentSettingsLookupService.
    """

    repository: AgentSizeRepository

    def resolve(self, agent_size_id: UUID | None = None) -> AgentSize:
        """The size an Agent starts on: the one its Organization chose, or the default.

        The values are read at each start, so editing a size, or moving the default under an
        Agent that never chose, reaches the Agent the next time it starts. A chosen size
        that was later disabled or withdrawn from the Organization still applies: those only
        stop it being chosen again.
        """
        if agent_size_id is not None:
            size = self.repository.get(agent_size_id)
            if size is not None:
                return size
        return self._default()

    def catalog(self) -> AgentSizeCatalog:
        sizes = {size.id: size for size in self.repository.list_all()}
        default = next((size for size in sizes.values() if size.is_default), None)
        if default is None:
            raise MissingDefaultAgentSize("The Agent Size catalog has no default size")
        return AgentSizeCatalog(sizes=sizes, default=default)

    def choosable(self, organization_id: UUID) -> list[AgentSize]:
        """The sizes an Organization's Agents may be put on: the default first, then the
        enabled sizes the platform allowed it, in catalog order."""
        allowed = self.repository.allowed_size_ids(organization_id)
        sizes = self.repository.list_all()
        default = next((size for size in sizes if size.is_default), None)
        if default is None:
            raise MissingDefaultAgentSize("The Agent Size catalog has no default size")
        return [default] + [size for size in sizes if size.id in allowed and size.enabled and not size.is_default]

    def is_choosable(self, organization_id: UUID, agent_size_id: UUID) -> bool:
        return any(size.id == agent_size_id for size in self.choosable(organization_id))

    def _default(self) -> AgentSize:
        default = self.repository.get_default()
        if default is None:
            raise MissingDefaultAgentSize("The Agent Size catalog has no default size")
        return default


def to_option(size: AgentSize) -> AgentSizeOption:
    return AgentSizeOption.model_validate(size, from_attributes=True)
