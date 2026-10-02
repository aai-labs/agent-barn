from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_settings.repository import AgentSettingsRepository


@inject
@singleton
@dataclass
class AgentSettingsLookupService:
    """Read-only Agent Settings resolution for other domains' services.

    Lives in its own module importing nothing but the repository and config, so the
    services AgentSettingsService itself depends on (AgentService, for Agent counts,
    and OrganizationService, for the allowlist invariant) can inject it without an
    import cycle. Mirrors OrganizationLookupService.
    """

    repository: AgentSettingsRepository
    config: Config

    def get_default_model(self, organization_id: UUID) -> str | None:
        """The Organization's own default, or None when it follows the platform."""
        settings = self.repository.get_for_org(organization_id)
        return settings.default_model if settings else None

    def resolve_default_model(self, organization_id: UUID) -> str:
        """The model an Agent without an explicit override runs on.

        Falls back to the install-wide AGENT_DEFAULT_MODEL rather than snapshotting
        it, so an Organization that never set a default follows platform upgrades.
        Never raises: a missing Organization resolves to the platform default, and
        callers that care about existence check it separately.
        """
        return self.get_default_model(organization_id) or self.config.agent_default_model

    def get_default_agent_llm_budget(self, organization_id: UUID) -> float | None:
        """The Organization's own default Agent spend limit, or None when it follows
        the platform's."""
        settings = self.repository.get_for_org(organization_id)
        return settings.default_agent_llm_budget_usd if settings else None

    def resolve_default_agent_llm_budget(self, organization_id: UUID) -> float:
        """The limit an Agent without one of its own is held to (before the
        Organization's own limit caps it). Tracks AGENT_DEFAULT_LLM_BUDGET_USD while
        the Organization has not chosen, like the default model does."""
        own = self.get_default_agent_llm_budget(organization_id)
        return own if own is not None else self.config.agent_default_llm_budget_usd
