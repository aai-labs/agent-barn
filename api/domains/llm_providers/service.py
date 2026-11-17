from dataclasses import dataclass

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.llm_providers.models import (
    KNOWN_PROVIDER_NAMES,
    OPENROUTER_ROUTE_API_BASE,
    OPENROUTER_ROUTE_ID,
    OPENROUTER_ROUTE_MODEL,
    OPENROUTER_ROUTE_ORDER,
    OPENROUTER_SLUG,
    LlmProviderConnection,
    LlmProviderConnectionCreate,
    LlmProviderConnectionRead,
    OpenRouterConnectionRead,
    OpenRouterKeyUpdate,
    ProviderType,
)
from api.domains.llm_providers.repository import ConnectionAlreadyExists, ConnectionNotFound, LlmProviderRepository
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.llm_provider_keys.checker import LlmProviderKeyChecker, LlmProviderUnreachable
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
    key_checker: LlmProviderKeyChecker

    def list_connections(self, context: CurrentUserContext) -> list[LlmProviderConnectionRead]:
        self.authority.require_platform_admin(context.user)
        return [self._to_read(connection, updated_by) for connection, updated_by in self.repository.list_active()]

    def add_connection(
        self, data: LlmProviderConnectionCreate, context: CurrentUserContext
    ) -> LlmProviderConnectionRead:
        self.authority.require_platform_admin(context.user)
        provider_type = data.provider_type
        slug = provider_type.value
        name = KNOWN_PROVIDER_NAMES[provider_type]
        if provider_type == ProviderType.OPENROUTER or self.repository.find_active(slug) is not None:
            raise HTTPException(409, f"{name} is already connected.")
        api_key = data.api_key.get_secret_value()
        try:
            accepted = self.key_checker.check(provider_type, api_key)
        except LlmProviderUnreachable:
            raise HTTPException(503, f"{name} could not be reached to check the key. Nothing was saved.") from None
        if not accepted:
            raise HTTPException(422, f"{name} did not accept this key. Nothing was saved.")
        try:
            ids = self.repository.add(
                slug,
                name,
                provider_type,
                encrypt_token(api_key, self.config.agent_token_encryption_key),
                api_key[-4:],
                context.user.id,
                context.user.full_name or context.user.email,
            )
        except ConnectionAlreadyExists:
            raise HTTPException(409, f"{name} is already connected.") from None
        self.dispatcher.enqueue_immediate(ids)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, f"The {name} connection does not exist.")
        return self._to_read(*found)

    def _to_read(self, connection: LlmProviderConnection, updated_by: str | None) -> LlmProviderConnectionRead:
        has_api_key = connection.api_key_encrypted is not None
        return LlmProviderConnectionRead(
            slug=connection.slug,
            name=connection.name,
            provider_type=connection.provider_type,
            base_url=connection.base_url,
            has_api_key=has_api_key,
            api_key_last4=connection.api_key_last4,
            updated_at=connection.updated_at if has_api_key else None,
            updated_by=updated_by if has_api_key else None,
            env_key_configured=bool(self.config.openrouter_api_key) and connection.slug == OPENROUTER_SLUG,
        )

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
                context.user.id,
                context.user.full_name or context.user.email,
                apply,
            )
        except ConnectionNotFound:
            raise HTTPException(404, "The OpenRouter connection does not exist.") from None
        self.dispatcher.enqueue_immediate(ids)
        return self.read_openrouter(context)
