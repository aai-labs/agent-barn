from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.organizations.repository import OrganizationRepository


@inject
@singleton
@dataclass
class OrganizationLookupService:
    """Read-only organization lookups for other domains' services.

    Lives in its own module, importing nothing but the repository, so that
    services which OrganizationService itself depends on (e.g. AgentService,
    via the delete-org guardrail) can inject it without an import cycle.
    """

    repository: OrganizationRepository

    def get_name(self, organization_id: UUID) -> str:
        organization = self.repository.get(organization_id)
        return organization.name if organization else ""

    def get_allowed_models(self, organization_id: UUID) -> list[str] | None:
        """The org's per-org model allowlist, or None if the org doesn't exist.

        None (missing org) is distinct from [] (org exists but allows nothing),
        so callers can raise 404 vs. reject the model accordingly.
        """
        organization = self.repository.get(organization_id)
        return organization.allowed_models if organization else None
