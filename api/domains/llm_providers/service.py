import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from urllib.parse import urlsplit

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.llm_providers.models import (
    BASE_URL_PROVIDER_TYPES,
    KNOWN_PROVIDER_NAMES,
    MAX_BASE_URL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_SLUG_LENGTH,
    OPENROUTER_ROUTE_API_BASE,
    OPENROUTER_ROUTE_ID,
    OPENROUTER_ROUTE_MODEL,
    OPENROUTER_ROUTE_ORDER,
    OPENROUTER_SLUG,
    SLUG_PATTERN,
    LlmProviderConnection,
    LlmProviderConnectionCreate,
    LlmProviderConnectionRead,
    LlmProviderKeyReplace,
    OpenRouterConnectionRead,
    OpenRouterKeyUpdate,
    ProviderType,
)
from api.domains.llm_providers.repository import (
    ConnectionAlreadyExists,
    ConnectionChanged,
    ConnectionNotFound,
    LlmProviderRepository,
)
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.llm_provider_keys.checker import (
    BaseUrlNotAnApi,
    BaseUrlNotPublic,
    LlmProviderKeyChecker,
    LlmProviderUnreachable,
)
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError

SLUG_FORMAT = f"The slug must be at most {MAX_SLUG_LENGTH} lowercase letters, digits and single hyphens."
SLUG_IS_A_PROVIDER = "The slug can't be a provider's name."
SLUG_TAKEN = "That slug is in use or was used before. Choose another."
NAME_FORMAT = f"Enter a name of at most {MAX_NAME_LENGTH} characters."
BASE_URL_NOT_PUBLIC = "The base URL must be a public HTTPS address. Nothing was saved."
BASE_URL_EXTRAS = "The base URL can't contain credentials, a query or a fragment. Nothing was saved."
BASE_URL_NOT_AN_API = "The base URL did not answer like a model API. Nothing was saved."
BASE_URL_NOT_TAKEN = "Only Azure and Custom connections take a base URL."
NOT_FOUND = "That connection does not exist."
CHANGED_WHILE_CHECKING = "The connection changed while the key was checked. Nothing was saved."
PROVIDER_TYPE_NAMES = frozenset(provider_type.value for provider_type in ProviderType)


def _own_connection_fields(data: LlmProviderConnectionCreate) -> tuple[str, str, str]:
    """The slug, trimmed name and base URL of an Azure or Custom connection, or a 422 naming the
    rule one of them breaks. The messages are fixed, so a refusal never echoes what was sent."""
    slug, name = data.slug or "", (data.name or "").strip()
    if len(slug) > MAX_SLUG_LENGTH or re.fullmatch(SLUG_PATTERN, slug) is None:
        raise HTTPException(422, SLUG_FORMAT)
    if slug in PROVIDER_TYPE_NAMES:
        raise HTTPException(422, SLUG_IS_A_PROVIDER)
    if not name or len(name) > MAX_NAME_LENGTH:
        raise HTTPException(422, NAME_FORMAT)
    return slug, name, _checked_base_url(data.base_url or "")


def _checked_base_url(value: str) -> str:
    """The base URL without surrounding spaces or a trailing `/`, or a 422 naming the rule it breaks."""
    base_url = value.strip().rstrip("/")
    if len(base_url) > MAX_BASE_URL_LENGTH or any(char.isspace() or not char.isprintable() for char in base_url):
        raise HTTPException(422, BASE_URL_NOT_PUBLIC)
    try:
        parts = urlsplit(base_url)
        https_with_host = parts.scheme == "https" and bool(parts.hostname) and parts.port != 0
    except ValueError:
        raise HTTPException(422, BASE_URL_NOT_PUBLIC) from None
    if not https_with_host:
        raise HTTPException(422, BASE_URL_NOT_PUBLIC)
    if parts.username is not None or parts.password is not None or "?" in base_url or "#" in base_url:
        raise HTTPException(422, BASE_URL_EXTRAS)
    return base_url


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
        api_key = data.api_key.get_secret_value()
        if provider_type in BASE_URL_PROVIDER_TYPES:
            slug, name, base_url = _own_connection_fields(data)
            already_used = SLUG_TAKEN
            if self.repository.slug_used(slug):
                raise HTTPException(409, already_used)
            check = partial(self.key_checker.check, provider_type, api_key, base_url)
        else:
            slug, name, base_url = provider_type.value, KNOWN_PROVIDER_NAMES[provider_type], None
            already_used = f"{name} is already connected."
            if provider_type == ProviderType.OPENROUTER or self.repository.find_active(slug) is not None:
                raise HTTPException(409, already_used)
            check = partial(self.key_checker.check, provider_type, api_key)
        self._check_key(name, check)
        try:
            ids = self.repository.add(
                slug,
                name,
                provider_type,
                base_url,
                encrypt_token(api_key, self.config.agent_token_encryption_key),
                api_key[-4:],
                context.user.id,
                context.user.full_name or context.user.email,
            )
        except ConnectionAlreadyExists:
            raise HTTPException(409, already_used) from None
        self.dispatcher.enqueue_immediate(ids)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, f"The {name} connection does not exist.")
        return self._to_read(*found)

    def replace_key(
        self, slug: str, data: LlmProviderKeyReplace, context: CurrentUserContext
    ) -> LlmProviderConnectionRead:
        self.authority.require_platform_admin(context.user)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, NOT_FOUND)
        connection = found[0]
        provider_type = connection.provider_type
        takes_base_url = provider_type in BASE_URL_PROVIDER_TYPES
        if data.base_url is not None and not takes_base_url:
            raise HTTPException(422, BASE_URL_NOT_TAKEN)
        base_url = _checked_base_url(data.base_url) if data.base_url is not None else connection.base_url
        api_key = data.api_key.get_secret_value()
        apply = None
        if provider_type == ProviderType.OPENROUTER:
            self._check_openrouter_key(api_key)
            apply = partial(self._route_openrouter_key, api_key)
        elif base_url is not None:
            self._check_key(connection.name, partial(self.key_checker.check, provider_type, api_key, base_url))
        else:
            self._check_key(connection.name, partial(self.key_checker.check, provider_type, api_key))
        try:
            ids = self.repository.replace_key(
                slug,
                encrypt_token(api_key, self.config.agent_token_encryption_key),
                api_key[-4:],
                context.user.id,
                context.user.full_name or context.user.email,
                seen_base_url=connection.base_url,
                base_url=base_url,
                apply=apply,
            )
        except ConnectionNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        except ConnectionChanged:
            raise HTTPException(409, CHANGED_WHILE_CHECKING) from None
        self.dispatcher.enqueue_immediate(ids)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, NOT_FOUND)
        return self._to_read(*found)

    @staticmethod
    def _check_key(name: str, check: Callable[[], bool]) -> None:
        try:
            accepted = check()
        except LlmProviderUnreachable:
            raise HTTPException(503, f"{name} could not be reached to check the key. Nothing was saved.") from None
        except BaseUrlNotPublic:
            raise HTTPException(422, BASE_URL_NOT_PUBLIC) from None
        except BaseUrlNotAnApi:
            raise HTTPException(422, BASE_URL_NOT_AN_API) from None
        if not accepted:
            raise HTTPException(422, f"{name} did not accept this key. Nothing was saved.")

    def _check_openrouter_key(self, api_key: str) -> None:
        try:
            accepted = self.openrouter.check_key(api_key)
        except OpenRouterError:
            raise HTTPException(
                503, "OpenRouter could not be reached to check the key. Your key was not changed."
            ) from None
        if not accepted:
            raise HTTPException(422, "OpenRouter did not accept this key. Your key was not changed.")

    def _route_openrouter_key(self, api_key: str) -> None:
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
        self.replace_key(OPENROUTER_SLUG, LlmProviderKeyReplace(api_key=data.api_key), context)
        return self.read_openrouter(context)
