from dataclasses import dataclass

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.llm_providers.models import OPENROUTER_SLUG, OpenRouterConnectionRead
from api.domains.llm_providers.repository import LlmProviderRepository
from api.domains.platform_admin.service import PlatformAdminService


@inject
@singleton
@dataclass
class PlatformLlmProviderService:
    repository: LlmProviderRepository
    authority: PlatformAdminService
    config: Config

    def read_openrouter(self, context: CurrentUserContext) -> OpenRouterConnectionRead:
        self.authority.require_platform_admin(context.user)
        found = self.repository.find_active(OPENROUTER_SLUG)
        if found is None:
            raise HTTPException(404, "The OpenRouter connection does not exist.")
        connection, updated_by = found
        has_api_key = connection.api_key_encrypted is not None
        return OpenRouterConnectionRead(
            has_api_key=has_api_key,
            api_key_last4=connection.api_key_last4,
            key_source=connection.key_source,
            updated_at=connection.updated_at if has_api_key else None,
            updated_by=updated_by if has_api_key else None,
            env_key_configured=bool(self.config.openrouter_api_key),
        )
