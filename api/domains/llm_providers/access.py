"""Provider Access: which Organizations may use an LLM Provider Connection."""

from collections.abc import Collection
from uuid import UUID

from api.domains.llm_providers.models import OrganizationAccess

NO_LLM_PROVIDER = "This organization has no LLM provider. Ask a Platform Administrator."
PROVIDER_NOT_OPEN = "This organization can't use {name}. Ask a Platform Administrator."
MODEL_NOT_STORED = "Model '{model}' is not one of {name}'s models."
_GATEWAY_PREFIX = "litellm/"


class ProviderNotOpen(Exception):
    def __init__(self, connection_name: str | None = None) -> None:
        super().__init__(connection_name)
        self.connection_name = connection_name


class UnknownConnection(Exception):
    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.model = model


class ModelNotStored(Exception):
    def __init__(self, connection_name: str, model: str) -> None:
        super().__init__(connection_name, model)
        self.connection_name = connection_name
        self.model = model


def connection_slug(name: str) -> str:
    """The slug of the connection a pool model (`<slug>/<model>`) or a stored model
    (`litellm/<slug>/<model>`) names."""
    return name.removeprefix(_GATEWAY_PREFIX).split("/", 1)[0]


def connection_model_id(name: str) -> str:
    """The model id a pool model or a stored model names on its connection."""
    return name.removeprefix(_GATEWAY_PREFIX).partition("/")[2]


def can_use(mode: OrganizationAccess, listed: Collection[UUID], organization_id: UUID | None) -> bool:
    """Whether the Organization may use a connection with this mode and these listed Organizations.
    `None` is an Organization not created yet, which no list names."""
    match mode:
        case OrganizationAccess.ALL:
            return True
        case OrganizationAccess.NONE:
            return False
        case OrganizationAccess.ALL_EXCEPT:
            return organization_id not in listed
        case OrganizationAccess.ONLY:
            return organization_id in listed
