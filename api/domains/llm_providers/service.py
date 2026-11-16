from dataclasses import dataclass

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.llm_providers.models import (
    OPENROUTER_ROUTE_API_BASE,
    OPENROUTER_ROUTE_ID,
    OPENROUTER_ROUTE_MODEL,
    OPENROUTER_ROUTE_ORDER,
    OPENROUTER_SLUG,
    KeySource,
    OpenRouterConnectionRead,
    OpenRouterKeyUpdate,
)
from api.domains.llm_providers.repository import ConnectionNotFound, LlmProviderRepository
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError


@inject
@singleton
@dataclass
class PlatformLlmProviderService:
    repository: LlmProviderRepository
    authority: PlatformAdminService
    config: Config
    openrouter: OpenRouterClient
    litellm: LiteLLMClient
    dispatcher: EventDeliveryDispatcher

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

    def replace_openrouter_key(
        self, data: OpenRouterKeyUpdate, context: CurrentUserContext
    ) -> OpenRouterConnectionRead:
        self.authority.require_platform_admin(context.user)
        api_key = data.api_key.get_secret_value()
        try:
            accepted = self.openrouter.check_key(api_key)
        except OpenRouterError:
            raise HTTPException(
                503, "OpenRouter could not be reached to check the key. Your key was not changed."
            ) from None
        if not accepted:
            raise HTTPException(422, "OpenRouter did not accept this key. Your key was not changed.")

        def apply() -> None:
            try:
                self.litellm.upsert_model_deployment(
                    model_name=OPENROUTER_ROUTE_MODEL,
                    litellm_params={
                        "model": OPENROUTER_ROUTE_MODEL,
                        "api_key": api_key,
                        "api_base": OPENROUTER_ROUTE_API_BASE,
                        "order": OPENROUTER_ROUTE_ORDER,
                    },
                    model_info={"id": OPENROUTER_ROUTE_ID, "disable_background_health_check": True},
                )
            except LiteLLMError:
                raise HTTPException(503, "The model proxy could not be updated. Your key was not changed.") from None

        try:
            ids = self.repository.replace_key(
                OPENROUTER_SLUG,
                encrypt_token(api_key, self.config.agent_token_encryption_key),
                api_key[-4:],
                KeySource.ADMIN,
                context.user.id,
                context.user.full_name or context.user.email,
                apply,
            )
        except ConnectionNotFound:
            raise HTTPException(404, "The OpenRouter connection does not exist.") from None
        self.dispatcher.enqueue_immediate(ids)
        return self.read_openrouter(context)
