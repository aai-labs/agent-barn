import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from urllib.parse import urlsplit

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.llm_providers.litellm_deployments import (
    LiteLLMDeployment,
    build_model_deployment,
    model_route_prefix,
)
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
    PRICE_SCALE,
    SLUG_PATTERN,
    LlmProviderCatalogueEntryRead,
    LlmProviderConnection,
    LlmProviderConnectionCreate,
    LlmProviderConnectionRead,
    LlmProviderKeyReplace,
    LlmProviderModel,
    LlmProviderModelRead,
    ProviderType,
)
from api.domains.llm_providers.repository import (
    ConnectionAlreadyExists,
    ConnectionChanged,
    ConnectionNotFound,
    LlmProviderRepository,
)
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMModelPrice, litellm_price_key
from api.infrastructure.llm_provider_catalogue.catalogue import (
    LlmProviderCatalogue,
    ProviderListRefused,
    ProviderListUnreachable,
    ProviderListUnreadable,
)
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
OPENROUTER_FIXED = "OpenRouter can't be deleted."
MODELS_NOT_STORED = "OpenRouter's models are not stored."
AZURE_NOT_LISTED = "Azure deployments are added by name."
PRICE_LIST_UNREADABLE = "The model proxy's price list could not be read."
CHANGED_WHILE_CHECKING = "The connection changed while the key was checked. Nothing was saved."
KEY_NOT_ROUTED = "The model proxy could not be updated. Your key was not changed."
ROUTES_NOT_REMOVED = "The model proxy could not be updated. Nothing was deleted."
PROVIDER_TYPE_NAMES = frozenset(provider_type.value for provider_type in ProviderType)
CHAT_MODE = "chat"
PRICE_STEP = Decimal(1).scaleb(-PRICE_SCALE)


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


def _exact(price: Decimal) -> Decimal:
    """The price as `NUMERIC(24,18)` stores it: Postgres rounds ties away from zero."""
    return price.quantize(PRICE_STEP, ROUND_HALF_UP)


def _catalogue_entry(
    provider_type: ProviderType,
    model_id: str,
    prices: dict[str, LiteLLMModelPrice],
    stored: LlmProviderModel | None,
) -> LlmProviderCatalogueEntryRead:
    """The model with LiteLLM's chat prices for it, a missing cache price taken as the input price."""
    key = litellm_price_key(provider_type, model_id)
    price = None if key is None else prices.get(key)
    if price is None or price.mode != CHAT_MODE:
        return LlmProviderCatalogueEntryRead(model_id=model_id, stored=stored is not None, prices_differ=False)
    input_price = _exact(price.input_cost_per_token)
    listed = (
        input_price,
        _exact(price.output_cost_per_token),
        input_price if price.cache_read_input_token_cost is None else _exact(price.cache_read_input_token_cost),
        input_price if price.cache_creation_input_token_cost is None else _exact(price.cache_creation_input_token_cost),
    )
    differs = stored is not None and listed != (
        stored.input_cost_per_token,
        stored.output_cost_per_token,
        stored.cache_read_input_token_cost,
        stored.cache_creation_input_token_cost,
    )
    output_price, cache_read, cache_creation = listed[1:]
    return LlmProviderCatalogueEntryRead(
        model_id=model_id,
        stored=stored is not None,
        litellm_price_key=price.key,
        input_cost_per_token=input_price,
        output_cost_per_token=output_price,
        cache_read_input_token_cost=cache_read,
        cache_creation_input_token_cost=cache_creation,
        prices_differ=differs,
    )


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
    catalogue: LlmProviderCatalogue

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
        if provider_type == ProviderType.OPENROUTER:
            self._check_openrouter_key(api_key)
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
                apply=partial(self._route_key, api_key),
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

    def list_models(self, slug: str, context: CurrentUserContext) -> list[LlmProviderModelRead]:
        self.authority.require_platform_admin(context.user)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, NOT_FOUND)
        connection = found[0]
        if connection.provider_type == ProviderType.OPENROUTER:
            raise HTTPException(409, MODELS_NOT_STORED)
        return [
            LlmProviderModelRead.model_validate(model, from_attributes=True)
            for model in self.repository.list_models(connection.id)
        ]

    def read_model_catalogue(self, slug: str, context: CurrentUserContext) -> list[LlmProviderCatalogueEntryRead]:
        self.authority.require_platform_admin(context.user)
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, NOT_FOUND)
        connection = found[0]
        if connection.provider_type == ProviderType.OPENROUTER:
            raise HTTPException(409, MODELS_NOT_STORED)
        if connection.provider_type == ProviderType.AZURE:
            raise HTTPException(409, AZURE_NOT_LISTED)
        if connection.api_key_encrypted is None:
            raise HTTPException(409, f"{connection.name} has no key.")
        api_key = decrypt_token(connection.api_key_encrypted, self.config.agent_token_encryption_key)
        model_ids = self._list_provider_models(connection, api_key)
        try:
            prices = self.litellm.get_model_prices()
        except LiteLLMError:
            raise HTTPException(503, PRICE_LIST_UNREADABLE) from None
        stored = {model.model_id: model for model in self.repository.list_models(connection.id)}
        return [
            _catalogue_entry(connection.provider_type, model_id, prices, stored.get(model_id)) for model_id in model_ids
        ]

    def delete_connection(self, slug: str, context: CurrentUserContext) -> None:
        self.authority.require_platform_admin(context.user)
        if slug == OPENROUTER_SLUG:
            raise HTTPException(409, OPENROUTER_FIXED)
        try:
            ids = self.repository.delete(
                slug, context.user.id, context.user.full_name or context.user.email, apply=self._remove_routes
            )
        except ConnectionNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        self.dispatcher.enqueue_immediate(ids)

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

    def _list_provider_models(self, connection: LlmProviderConnection, api_key: str) -> list[str]:
        name = connection.name
        try:
            if connection.base_url is not None:
                return self.catalogue.list_models(connection.provider_type, api_key, connection.base_url)
            return self.catalogue.list_models(connection.provider_type, api_key)
        except ProviderListRefused:
            raise HTTPException(
                409, f"{name} did not accept the stored key. Replace the key, then try again."
            ) from None
        except ProviderListUnreachable:
            raise HTTPException(503, f"{name} could not be reached to list its models.") from None
        except ProviderListUnreadable:
            raise HTTPException(502, f"{name}'s model list could not be read.") from None

    def _check_openrouter_key(self, api_key: str) -> None:
        try:
            accepted = self.openrouter.check_key(api_key)
        except OpenRouterError:
            raise HTTPException(
                503, "OpenRouter could not be reached to check the key. Your key was not changed."
            ) from None
        if not accepted:
            raise HTTPException(422, "OpenRouter did not accept this key. Your key was not changed.")

    def _route_key(self, api_key: str, connection: LlmProviderConnection, models: list[LlmProviderModel]) -> None:
        try:
            if connection.provider_type == ProviderType.OPENROUTER:
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
            else:
                self._reconcile_routes(
                    connection, [build_model_deployment(connection, model, api_key) for model in models]
                )
        except LiteLLMError:
            raise HTTPException(503, KEY_NOT_ROUTED) from None

    def _remove_routes(self, connection: LlmProviderConnection) -> None:
        try:
            self._reconcile_routes(connection, [])
        except LiteLLMError:
            raise HTTPException(503, ROUTES_NOT_REMOVED) from None

    def _reconcile_routes(self, connection: LlmProviderConnection, wanted: list[LiteLLMDeployment]) -> None:
        listed = self.litellm.list_model_deployments(model_route_prefix(connection.id))
        for deployment in wanted:
            self.litellm.upsert_model_deployment(
                model_name=deployment.model_name,
                litellm_params=deployment.litellm_params,
                model_info=deployment.model_info,
            )
        wanted_ids = {deployment.model_info["id"] for deployment in wanted}
        for route in listed:
            if route["model_info"]["id"] not in wanted_ids:
                self.litellm.delete_model_deployment(route["model_info"]["id"])

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
