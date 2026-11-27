from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session

from api.core.config import Config
from api.domains.llm_providers.access import ProviderNotOpen, can_use
from api.domains.llm_providers.models import (
    OPENROUTER_SLUG,
    LlmProviderConnection,
    LlmProviderModel,
    OrganizationAccess,
)
from api.domains.llm_providers.repository import LlmProviderRepository
from api.infrastructure.crypto import decrypt_token


def _open(access: tuple[OrganizationAccess, frozenset[UUID]] | None, organization_id: UUID | None) -> bool:
    return access is not None and can_use(*access, organization_id)


@inject
@singleton
@dataclass
class OpenRouterKeyLookup:
    repository: LlmProviderRepository
    config: Config

    def api_key(self) -> str:
        """The stored OpenRouter key, else the one in the environment, else empty."""
        found = self.repository.find_active(OPENROUTER_SLUG)
        if found is not None and found[0].api_key_encrypted is not None:
            return decrypt_token(found[0].api_key_encrypted, self.config.agent_token_encryption_key)
        return self.config.openrouter_api_key


@inject
@singleton
@dataclass
class LlmProviderAccessLookup:
    """Provider Access for the domains that use a connection on an Organization's behalf."""

    repository: LlmProviderRepository

    def can_use(self, slug: str, organization_id: UUID) -> bool:
        """Whether the Organization may use the live connection now, read without a lock."""
        return _open(self.repository.access(slug, organization_id), organization_id)

    def open_models(self, organization_id: UUID) -> list[tuple[LlmProviderConnection, list[LlmProviderModel]]]:
        """The live connections the Organization may use now, read without a lock, OpenRouter first and
        then by name, each with its stored models by model id."""
        return self.repository.open_models(organization_id)

    def require_open(self, session: Session, slug: str, organization_id: UUID) -> None:
        """Raises ProviderNotOpen unless the Organization may use the live connection, checked in the
        caller's transaction under the connection's shared lock, held until that transaction ends."""
        if not _open(self.repository.access_held(session, slug, organization_id), organization_id):
            raise ProviderNotOpen

    def initial_allowed_models(self, session: Session, default: str) -> list[str]:
        """The allowlist a new Organization starts with: the default model while OpenRouter is open to
        Organizations not created yet, else none. Checked as `require_open` is."""
        return [default] if _open(self.repository.access_held(session, OPENROUTER_SLUG, None), None) else []
