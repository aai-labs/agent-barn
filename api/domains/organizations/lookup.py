from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.organizations.repository import OrganizationRepository


@dataclass(frozen=True)
class OrganizationLlmLimit:
    """The limit in force on an Organization's team, and the window it renews on.

    Agent limits are held beneath `limit_usd` and share `window`, so the Organization
    and every one of its Agents renew at the same moment.
    """

    limit_usd: float
    window: str
    # When the Organization's window next renews — and so every Agent key's, since
    # they share it. None until the proxy has reported one.
    renews_at: datetime | None = None


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

    def get_llm_limit(self, organization_id: UUID) -> OrganizationLlmLimit | None:
        """None when the Organization does not exist."""
        organization = self.repository.get(organization_id)
        if organization is None:
            return None
        return OrganizationLlmLimit(
            limit_usd=organization.effective_llm_budget_usd,
            window=organization.llm_budget_duration,
            renews_at=organization.llm_budget_renews_at,
        )
