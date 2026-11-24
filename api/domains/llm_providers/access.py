"""Provider Access: which Organizations may use an LLM Provider Connection."""

from collections.abc import Collection
from uuid import UUID

from api.domains.llm_providers.models import OrganizationAccess


class ProviderNotOpen(Exception):
    pass


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
