from dataclasses import dataclass

import httpx
from injector import singleton

from api.domains.llm_providers.models import BASE_URL_PROVIDER_TYPES, ProviderType
from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address

TIMEOUT_SECONDS = 10
UNREACHABLE_MESSAGE = "The provider could not be reached to check the key"
BASE_URL_NOT_PUBLIC_MESSAGE = "The base URL must be a public HTTPS address"
REFUSED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


@dataclass(frozen=True)
class _Endpoint:
    url: str
    header: str
    prefix: str = ""


_BEARER = ("Authorization", "Bearer ")
_ENDPOINTS = {
    ProviderType.ANTHROPIC: _Endpoint("https://api.anthropic.com/v1/models", "x-api-key"),
    ProviderType.OPENAI: _Endpoint("https://api.openai.com/v1/models", *_BEARER),
    ProviderType.GEMINI: _Endpoint("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key"),
    ProviderType.XAI: _Endpoint("https://api.x.ai/v1/models", *_BEARER),
    ProviderType.DEEPSEEK: _Endpoint("https://api.deepseek.com/models", *_BEARER),
    ProviderType.FIREWORKS: _Endpoint("https://api.fireworks.ai/v1/accounts", *_BEARER),
    ProviderType.NOVITA: _Endpoint("https://api.novita.ai/openai/v1/models", *_BEARER),
    ProviderType.AZURE: _Endpoint("/openai/v1/models", "api-key"),
    ProviderType.CUSTOM: _Endpoint("/models", *_BEARER),
}
_EXTRA_REFUSED_STATUSES = {ProviderType.GEMINI: frozenset({httpx.codes.BAD_REQUEST})}


class LlmProviderKeyCheckError(Exception):
    """The key could not be checked. The message is fixed and never carries the key."""


class LlmProviderUnreachable(LlmProviderKeyCheckError):
    def __init__(self) -> None:
        super().__init__(UNREACHABLE_MESSAGE)


class BaseUrlNotPublic(LlmProviderKeyCheckError):
    def __init__(self) -> None:
        super().__init__(BASE_URL_NOT_PUBLIC_MESSAGE)


@singleton
class LlmProviderKeyChecker:
    def check(self, provider_type: ProviderType, api_key: str, base_url: str | None = None) -> bool:
        """Whether the provider accepts the key.

        Raises ``LlmProviderUnreachable`` when the provider gives no answer that settles it,
        and ``BaseUrlNotPublic`` when an Azure or Custom base URL is not a public HTTPS address.
        """
        endpoint = _ENDPOINTS.get(provider_type)
        if endpoint is None:
            raise ValueError(f"{provider_type} keys are not checked by LlmProviderKeyChecker")
        takes_base_url = provider_type in BASE_URL_PROVIDER_TYPES
        if takes_base_url != (base_url is not None):
            raise ValueError("Only Azure and Custom connections have a base URL, and they must")

        url = f"{base_url.rstrip('/')}{endpoint.url}" if base_url is not None else endpoint.url
        try:
            pinned = pin_to_public_address(url)
        except NonPublicDestination:
            if takes_base_url:
                raise BaseUrlNotPublic from None
            raise LlmProviderUnreachable from None

        headers = {**pinned.headers, endpoint.header: f"{endpoint.prefix}{api_key}"}
        try:
            with (
                httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
                client.stream("GET", pinned.url, headers=headers, extensions=pinned.extensions) as response,
            ):
                status_code = response.status_code
        except httpx.HTTPError:
            raise LlmProviderUnreachable from None

        if status_code == httpx.codes.OK:
            return True
        if status_code in REFUSED_STATUSES | _EXTRA_REFUSED_STATUSES.get(provider_type, frozenset()):
            return False
        raise LlmProviderUnreachable
