from collections.abc import Callable, Collection
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session

from api.core.config import Config
from api.domains.llm_providers.access import (
    ModelNotStored,
    ProviderNotOpen,
    UnknownConnection,
    can_use,
    connection_model_id,
    connection_slug,
)
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


def _check_models(
    names: Collection[str],
    organization_id: UUID,
    read: Callable[[str], tuple[LlmProviderConnection, frozenset[UUID], frozenset[str]] | None],
) -> None:
    by_slug: dict[str, list[str]] = {}
    for name in names:
        by_slug.setdefault(connection_slug(name), []).append(name)
    for slug in sorted(by_slug):
        found = read(slug)
        if found is None:
            raise UnknownConnection(by_slug[slug][0])
        connection, listed, model_ids = found
        if not can_use(connection.organization_access, listed, organization_id):
            raise ProviderNotOpen(connection.name)
        if slug == OPENROUTER_SLUG:
            continue
        for name in by_slug[slug]:
            if connection_model_id(name) not in model_ids:
                raise ModelNotStored(connection.name, name)


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

    def check_models(self, names: Collection[str], organization_id: UUID) -> None:
        """Raises unless every named model's connection is live and open to the Organization and, off
        OpenRouter, the model is stored on it, read without a lock: UnknownConnection for a connection
        that isn't live, ProviderNotOpen for one not open to it, ModelNotStored for a model it
        doesn't store."""
        _check_models(names, organization_id, lambda slug: self.repository.pool_connection(slug, organization_id))

    def require_models(self, session: Session, names: Collection[str], organization_id: UUID) -> None:
        """As `check_models`, in the caller's transaction after taking each named connection's lock
        shared, in slug order, held until that transaction ends."""
        _check_models(
            names,
            organization_id,
            lambda slug: self.repository.pool_connection_held(session, slug, organization_id),
        )

    def initial_allowed_models(self, session: Session, default: str) -> list[str]:
        """The allowlist a new Organization starts with: the default model while OpenRouter is open to
        Organizations not created yet, else none. Checked as `require_open` is."""
        return [default] if _open(self.repository.access_held(session, OPENROUTER_SLUG, None), None) else []
