import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
    AZURE_DEPLOYMENT_PATTERN,
    BASE_URL_PROVIDER_TYPES,
    KNOWN_PROVIDER_NAMES,
    MAX_AZURE_DEPLOYMENT_LENGTH,
    MAX_BASE_URL_LENGTH,
    MAX_MODEL_ID_LENGTH,
    MAX_MODELS_PER_CONNECTION,
    MAX_NAME_LENGTH,
    MAX_SLUG_LENGTH,
    MODEL_ID_PATTERN,
    OPENROUTER_ROUTE_API_BASE,
    OPENROUTER_ROUTE_ID,
    OPENROUTER_ROUTE_MODEL,
    OPENROUTER_ROUTE_ORDER,
    OPENROUTER_SLUG,
    PRICE_PRECISION,
    PRICE_SCALE,
    SLUG_PATTERN,
    LlmProviderCatalogueEntryRead,
    LlmProviderConnection,
    LlmProviderConnectionCreate,
    LlmProviderConnectionRead,
    LlmProviderKeyReplace,
    LlmProviderModel,
    LlmProviderModelPrices,
    LlmProviderModelRead,
    LlmProviderModelsReplace,
    LlmProviderTypedPrices,
    PriceSource,
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
from api.infrastructure.litellm.client import (
    PRICE_KEY_PREFIXES,
    LiteLLMClient,
    LiteLLMError,
    LiteLLMModelPrice,
    litellm_price_key,
)
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
PRICE_LIST_UNREADABLE = "The model proxy's price list could not be read."
TOO_MANY_MODELS = f"A connection can have at most {MAX_MODELS_PER_CONNECTION} models. Nothing was saved."
MODEL_REPEATED = "A model can be listed only once. Nothing was saved."
AZURE_DEPLOYMENT_FORMAT = (
    f"A deployment name must be 1 to {MAX_AZURE_DEPLOYMENT_LENGTH} letters, digits or . _ - characters. "
    "Nothing was saved."
)
RUNS_MODEL_MISSING = "Say which model each deployment priced from LiteLLM runs. Nothing was saved."
RUNS_MODEL_NOT_TAKEN = "Only an Azure deployment priced from LiteLLM takes the model it runs. Nothing was saved."
MODEL_ID_FORMAT = (
    f"A model id must be 1 to {MAX_MODEL_ID_LENGTH} letters, digits or . _ : / - characters. Nothing was saved."
)
PRICE_CHOICE = 'Each model takes "litellm", "stored" or its four prices. Nothing was saved.'
PRICE_FORMAT = "Each price must be a number below 1,000,000 with at most 18 decimal places. Nothing was saved."
PRICE_RANGE = "Input and output prices must be above 0, and cache prices 0 or more. Nothing was saved."
NO_CHAT_PRICE = "LiteLLM has no chat price for one of these models; type its prices. Nothing was saved."
PRICES_NOT_STORED = "Only a stored model can keep its stored prices. Nothing was saved."
MODELS_CHANGED_WHILE_READING = "The connection changed while its models were read. Nothing was saved."
MODELS_NOT_ROUTED = "The model proxy could not be updated. Your models were not changed."
LITELLM_PRICE = "litellm"
STORED_PRICE = "stored"
PRICE_CHOICES = frozenset({LITELLM_PRICE, STORED_PRICE})
ROUTE_KEY_PARAM = "api_key"
AZURE_PRICE_KEY_PREFIX = f"{PRICE_KEY_PREFIXES[ProviderType.AZURE]}/"
CHANGED_WHILE_CHECKING = "The connection changed while the key was checked. Nothing was saved."
KEY_NOT_ROUTED = "The model proxy could not be updated. Your key was not changed."
ROUTES_NOT_REMOVED = "The model proxy could not be updated. Nothing was deleted."
PROVIDER_TYPE_NAMES = frozenset(provider_type.value for provider_type in ProviderType)
CHAT_MODE = "chat"
PRICE_STEP = Decimal(1).scaleb(-PRICE_SCALE)
MAX_PRICE = Decimal(10) ** (PRICE_PRECISION - PRICE_SCALE)


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


def _chat_price(
    provider_type: ProviderType, model_id: str, prices: dict[str, LiteLLMModelPrice]
) -> LiteLLMModelPrice | None:
    key = litellm_price_key(provider_type, model_id)
    price = None if key is None else prices.get(key)
    return price if price is not None and price.mode == CHAT_MODE else None


def _litellm_prices(price: LiteLLMModelPrice) -> LlmProviderModelPrices:
    """LiteLLM's chat price as it would be stored, a missing cache price taken as the input price."""
    input_price = _exact(price.input_cost_per_token)
    cache_read, cache_creation = (
        input_price if cache_price is None else _exact(cache_price)
        for cache_price in (price.cache_read_input_token_cost, price.cache_creation_input_token_cost)
    )
    return LlmProviderModelPrices(
        input_price,
        _exact(price.output_cost_per_token),
        cache_read,
        cache_creation,
        PriceSource.LITELLM,
        price.key,
    )


def _priced_entry(
    model_id: str, listed: LlmProviderModelPrices, stored: bool, prices_differ: bool
) -> LlmProviderCatalogueEntryRead:
    return LlmProviderCatalogueEntryRead(
        model_id=model_id,
        stored=stored,
        litellm_price_key=listed.litellm_price_key,
        input_cost_per_token=listed.input_cost_per_token,
        output_cost_per_token=listed.output_cost_per_token,
        cache_read_input_token_cost=listed.cache_read_input_token_cost,
        cache_creation_input_token_cost=listed.cache_creation_input_token_cost,
        prices_differ=prices_differ,
    )


def _catalogue_entry(
    provider_type: ProviderType,
    model_id: str,
    prices: dict[str, LiteLLMModelPrice],
    stored: LlmProviderModel | None,
) -> LlmProviderCatalogueEntryRead:
    price = _chat_price(provider_type, model_id, prices)
    if price is None:
        return LlmProviderCatalogueEntryRead(model_id=model_id, stored=stored is not None, prices_differ=False)
    listed = _litellm_prices(price)
    differs = stored is not None and listed.amounts() != LlmProviderModelPrices.of(stored).amounts()
    return _priced_entry(model_id, listed, stored is not None, differs)


def _azure_catalogue(
    prices: dict[str, LiteLLMModelPrice], stored: list[LlmProviderModel]
) -> list[LlmProviderCatalogueEntryRead]:
    """LiteLLM's Azure chat models, each by the model a deployment runs, marked stored when a
    deployment is priced from it, and differing when such a deployment stores other prices."""
    entries = []
    for key, price in sorted(prices.items()):
        if not key.startswith(AZURE_PRICE_KEY_PREFIX) or price.mode != CHAT_MODE:
            continue
        listed = _litellm_prices(price)
        deployments = [model for model in stored if model.litellm_price_key == key]
        differs = any(LlmProviderModelPrices.of(model).amounts() != listed.amounts() for model in deployments)
        entries.append(_priced_entry(key.removeprefix(AZURE_PRICE_KEY_PREFIX), listed, bool(deployments), differs))
    return entries


def _typed_price(value: str | None) -> Decimal:
    try:
        price = Decimal(value) if value is not None else None
    except InvalidOperation:
        price = None
    if price is None or not price.is_finite() or abs(price) >= MAX_PRICE or price.quantize(PRICE_STEP) != price:
        raise HTTPException(422, PRICE_FORMAT)
    return price


def _checked_price(price: str | LlmProviderTypedPrices) -> str | LlmProviderModelPrices:
    """`"litellm"`, `"stored"`, or the typed prices, or a 422 naming the rule they break."""
    if isinstance(price, str):
        if price not in PRICE_CHOICES:
            raise HTTPException(422, PRICE_CHOICE)
        return price
    input_price, output_price, cache_read, cache_creation = (
        _typed_price(value)
        for value in (
            price.input_cost_per_token,
            price.output_cost_per_token,
            price.cache_read_input_token_cost,
            price.cache_creation_input_token_cost,
        )
    )
    if input_price <= 0 or output_price <= 0 or cache_read < 0 or cache_creation < 0:
        raise HTTPException(422, PRICE_RANGE)
    return LlmProviderModelPrices(input_price, output_price, cache_read, cache_creation, PriceSource.MANUAL)


def _checked_choices(
    data: LlmProviderModelsReplace, provider_type: ProviderType
) -> list[tuple[str, str | LlmProviderModelPrices, str | None]]:
    """Each model id with its checked price and the model an Azure deployment runs, or a 422
    naming the rule the body breaks."""
    if len(data.models) > MAX_MODELS_PER_CONNECTION:
        raise HTTPException(422, TOO_MANY_MODELS)
    model_ids = [choice.model_id for choice in data.models]
    if provider_type == ProviderType.AZURE:
        if any(
            len(model_id) > MAX_AZURE_DEPLOYMENT_LENGTH or not re.fullmatch(AZURE_DEPLOYMENT_PATTERN, model_id)
            for model_id in model_ids
        ):
            raise HTTPException(422, AZURE_DEPLOYMENT_FORMAT)
    elif any(
        len(model_id) > MAX_MODEL_ID_LENGTH or not re.fullmatch(MODEL_ID_PATTERN, model_id) for model_id in model_ids
    ):
        raise HTTPException(422, MODEL_ID_FORMAT)
    if len(set(model_ids)) != len(model_ids):
        raise HTTPException(422, MODEL_REPEATED)
    checked = []
    for choice in data.models:
        price = _checked_price(choice.price)
        priced_by_runs_model = provider_type == ProviderType.AZURE and price == LITELLM_PRICE
        if priced_by_runs_model and choice.runs_model is None:
            raise HTTPException(422, RUNS_MODEL_MISSING)
        if not priced_by_runs_model and choice.runs_model is not None:
            raise HTTPException(422, RUNS_MODEL_NOT_TAKEN)
        checked.append((choice.model_id, price, choice.runs_model))
    return checked


def _route_matches(route: dict | None, deployment: LiteLLMDeployment) -> bool:
    """Whether LiteLLM's listed route already has every field the deployment sends. LiteLLM leaves
    the key out of its listing, so the key is compared by the fingerprint in `model_info`."""
    if route is None or route.get("model_name") != deployment.model_name:
        return False
    params, info = route.get("litellm_params") or {}, route.get("model_info") or {}
    return all(
        params.get(name) == value for name, value in deployment.litellm_params.items() if name != ROUTE_KEY_PARAM
    ) and all(info.get(name) == value for name, value in deployment.model_info.items())


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
        connection, _, api_key = self._model_connection(slug)
        if connection.provider_type == ProviderType.AZURE:
            return _azure_catalogue(self._model_prices(), self.repository.list_models(connection.id))
        model_ids = self._list_provider_models(connection, api_key)
        prices = self._model_prices()
        stored = {model.model_id: model for model in self.repository.list_models(connection.id)}
        return [
            _catalogue_entry(connection.provider_type, model_id, prices, stored.get(model_id)) for model_id in model_ids
        ]

    def replace_models(
        self, slug: str, data: LlmProviderModelsReplace, context: CurrentUserContext
    ) -> list[LlmProviderModelRead]:
        self.authority.require_platform_admin(context.user)
        connection, api_key_encrypted, api_key = self._model_connection(slug)
        choices = _checked_choices(data, connection.provider_type)
        stored_ids = {model.model_id for model in self.repository.list_models(connection.id)}
        if any(price == STORED_PRICE and model_id not in stored_ids for model_id, price, _ in choices):
            raise HTTPException(422, PRICES_NOT_STORED)
        if connection.provider_type != ProviderType.AZURE:
            listed = set(self._list_provider_models(connection, api_key))
            if any(model_id not in listed for model_id, _, _ in choices):
                raise HTTPException(422, f"{connection.name} does not list one of these models. Nothing was saved.")
        prices = self._model_prices() if any(price == LITELLM_PRICE for _, price, _ in choices) else {}
        wanted: list[tuple[str, LlmProviderModelPrices | None]] = []
        for model_id, price, runs_model in choices:
            if isinstance(price, LlmProviderModelPrices):
                wanted.append((model_id, price))
            elif price == STORED_PRICE:
                wanted.append((model_id, None))
            else:
                priced_as = model_id if runs_model is None else runs_model
                chat_price = _chat_price(connection.provider_type, priced_as, prices)
                if chat_price is None:
                    raise HTTPException(422, NO_CHAT_PRICE)
                wanted.append((model_id, _litellm_prices(chat_price)))
        try:
            ids = self.repository.replace_models(
                slug,
                context.user.id,
                context.user.full_name or context.user.email,
                seen_api_key_encrypted=api_key_encrypted,
                seen_base_url=connection.base_url,
                wanted=wanted,
                apply=partial(self._route_models, api_key),
            )
        except ConnectionNotFound:
            raise HTTPException(404, NOT_FOUND) from None
        except ConnectionChanged:
            raise HTTPException(409, MODELS_CHANGED_WHILE_READING) from None
        self.dispatcher.enqueue_immediate(ids)
        return [
            LlmProviderModelRead.model_validate(model, from_attributes=True)
            for model in self.repository.list_models(connection.id)
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

    def _model_connection(self, slug: str) -> tuple[LlmProviderConnection, str, str]:
        """The live connection whose models are stored, with its stored ciphertext and key; else a
        404 or 409."""
        found = self.repository.find_active(slug)
        if found is None:
            raise HTTPException(404, NOT_FOUND)
        connection = found[0]
        if connection.provider_type == ProviderType.OPENROUTER:
            raise HTTPException(409, MODELS_NOT_STORED)
        if connection.api_key_encrypted is None:
            raise HTTPException(409, f"{connection.name} has no key.")
        api_key = decrypt_token(connection.api_key_encrypted, self.config.agent_token_encryption_key)
        return connection, connection.api_key_encrypted, api_key

    def _model_prices(self) -> dict[str, LiteLLMModelPrice]:
        try:
            return self.litellm.get_model_prices()
        except LiteLLMError:
            raise HTTPException(503, PRICE_LIST_UNREADABLE) from None

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

    def _route_models(self, api_key: str, connection: LlmProviderConnection, models: list[LlmProviderModel]) -> None:
        try:
            self._reconcile_routes(
                connection, [build_model_deployment(connection, model, api_key) for model in models], only_changed=True
            )
        except LiteLLMError:
            raise HTTPException(503, MODELS_NOT_ROUTED) from None

    def _reconcile_routes(
        self, connection: LlmProviderConnection, wanted: list[LiteLLMDeployment], *, only_changed: bool = False
    ) -> None:
        """Write every wanted route, or with `only_changed` only those LiteLLM lists differently,
        then remove the connection's routes that are not wanted."""
        listed = {
            route["model_info"]["id"]: route
            for route in self.litellm.list_model_deployments(model_route_prefix(connection.id))
        }
        for deployment in wanted:
            if only_changed and _route_matches(listed.get(deployment.model_info["id"]), deployment):
                continue
            self.litellm.upsert_model_deployment(
                model_name=deployment.model_name,
                litellm_params=deployment.litellm_params,
                model_info=deployment.model_info,
            )
        wanted_ids = {deployment.model_info["id"] for deployment in wanted}
        for route_id in listed.keys() - wanted_ids:
            self.litellm.delete_model_deployment(route_id)

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
