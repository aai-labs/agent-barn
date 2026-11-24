from dataclasses import dataclass

import httpx
from injector import singleton

from api.domains.llm_providers.models import BASE_URL_PROVIDER_TYPES, ProviderType
from api.infrastructure.llm_provider_catalogue.catalogue import ANTHROPIC_VERSION
from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address

TIMEOUT_SECONDS = 10
UNREACHABLE_MESSAGE = "The provider could not be reached to check the key"
BASE_URL_NOT_PUBLIC_MESSAGE = "The base URL must be a public HTTPS address"
BASE_URL_NOT_AN_API_MESSAGE = "The base URL did not answer like a model API"
REFUSED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})
JSON_MEDIA_TYPE = "application/json"
JSON_MEDIA_TYPE_SUFFIX = "+json"
# An OpenAI-compatible server that lists its models without a key proves nothing about the key there.
# It is then sent an empty chat request with the key: servers check the key before the body, so a
# refused key is 401 or 403 and an accepted one 400 or 422 for the missing input, and nothing is generated.
CHAT_PROBE_PATH = "/chat/completions"
EMPTY_CHAT_REQUEST = b"{}"
BODY_REFUSED_STATUSES = frozenset({httpx.codes.BAD_REQUEST, httpx.codes.UNPROCESSABLE_ENTITY})


@dataclass(frozen=True)
class _Endpoint:
    url: str
    header: str
    prefix: str = ""
    headers: tuple[tuple[str, str], ...] = ()


_BEARER = ("Authorization", "Bearer ")
_ENDPOINTS = {
    ProviderType.ANTHROPIC: _Endpoint(
        "https://api.anthropic.com/v1/models", "x-api-key", headers=(("anthropic-version", ANTHROPIC_VERSION),)
    ),
    ProviderType.OPENAI: _Endpoint("https://api.openai.com/v1/models", *_BEARER),
    ProviderType.GEMINI: _Endpoint("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key"),
    ProviderType.XAI: _Endpoint("https://api.x.ai/v1/models", *_BEARER),
    ProviderType.DEEPSEEK: _Endpoint("https://api.deepseek.com/models", *_BEARER),
    ProviderType.FIREWORKS: _Endpoint("https://api.fireworks.ai/v1/accounts", *_BEARER),
    ProviderType.NOVITA: _Endpoint("https://api.novita.ai/v3/user", *_BEARER),
    ProviderType.AZURE: _Endpoint("/openai/v1/models", "api-key"),
    ProviderType.CUSTOM: _Endpoint("/models", *_BEARER),
}
_EXTRA_REFUSED_STATUSES = {
    ProviderType.GEMINI: frozenset({httpx.codes.BAD_REQUEST}),
    ProviderType.XAI: frozenset({httpx.codes.BAD_REQUEST}),
}


class LlmProviderKeyCheckError(Exception):
    """The key could not be checked. The message is fixed and never carries the key."""


class LlmProviderUnreachable(LlmProviderKeyCheckError):
    def __init__(self) -> None:
        super().__init__(UNREACHABLE_MESSAGE)


class BaseUrlNotPublic(LlmProviderKeyCheckError):
    def __init__(self) -> None:
        super().__init__(BASE_URL_NOT_PUBLIC_MESSAGE)


class BaseUrlNotAnApi(LlmProviderKeyCheckError):
    def __init__(self) -> None:
        super().__init__(BASE_URL_NOT_AN_API_MESSAGE)


def _is_json(content_type: str | None) -> bool:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    return media_type == JSON_MEDIA_TYPE or media_type.endswith(JSON_MEDIA_TYPE_SUFFIX)


@singleton
class LlmProviderKeyChecker:
    def check(self, provider_type: ProviderType, api_key: str, base_url: str | None = None) -> bool:
        """Whether the provider accepts the key.

        Raises ``LlmProviderUnreachable`` when the provider gives no answer that settles it,
        ``BaseUrlNotPublic`` when an Azure or Custom base URL is not a public HTTPS address, and
        ``BaseUrlNotAnApi`` when it answers with a redirect, a 404, or a success that is not JSON.
        A Custom endpoint that lists its models without any key is also sent an empty chat request
        with the key, since its list proves nothing about the key. Only the status and headers are
        read, never the body.
        """
        endpoint = _ENDPOINTS.get(provider_type)
        if endpoint is None:
            raise ValueError(f"{provider_type} keys are not checked by LlmProviderKeyChecker")
        takes_base_url = provider_type in BASE_URL_PROVIDER_TYPES
        if takes_base_url != (base_url is not None):
            raise ValueError("Only Azure and Custom connections have a base URL, and they must")

        root = base_url.rstrip("/") if base_url is not None else ""
        not_public = BaseUrlNotPublic if takes_base_url else LlmProviderUnreachable
        key_header = {endpoint.header: f"{endpoint.prefix}{api_key}"}
        list_url = f"{root}{endpoint.url}"
        status_code, content_type = _ask("GET", list_url, {**dict(endpoint.headers), **key_header}, not_public)
        if takes_base_url and (
            status_code == httpx.codes.NOT_FOUND
            or httpx.codes.is_redirect(status_code)
            or (status_code == httpx.codes.OK and not _is_json(content_type))
        ):
            raise BaseUrlNotAnApi
        if status_code in REFUSED_STATUSES | _EXTRA_REFUSED_STATUSES.get(provider_type, frozenset()):
            return False
        if status_code != httpx.codes.OK:
            raise LlmProviderUnreachable
        if provider_type is ProviderType.CUSTOM and _ask("GET", list_url, {}, not_public)[0] == httpx.codes.OK:
            return _chat_accepts(f"{root}{CHAT_PROBE_PATH}", key_header)
        return True


def _chat_accepts(url: str, key_header: dict[str, str]) -> bool:
    headers = {**key_header, "Content-Type": JSON_MEDIA_TYPE}
    status_code, _ = _ask("POST", url, headers, BaseUrlNotPublic, EMPTY_CHAT_REQUEST)
    if status_code in REFUSED_STATUSES:
        return False
    if httpx.codes.is_success(status_code) or status_code in BODY_REFUSED_STATUSES:
        return True
    if status_code == httpx.codes.NOT_FOUND:
        raise BaseUrlNotAnApi
    raise LlmProviderUnreachable


def _ask(
    method: str,
    url: str,
    headers: dict[str, str],
    not_public: type[LlmProviderKeyCheckError],
    content: bytes | None = None,
) -> tuple[int, str | None]:
    """The status and content type of one request pinned to a public address, raising `not_public`
    when the address is not one. The body is never read."""
    try:
        pinned = pin_to_public_address(url)
    except NonPublicDestination:
        raise not_public from None
    try:
        with (
            httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
            client.stream(
                method, pinned.url, headers={**pinned.headers, **headers}, content=content, extensions=pinned.extensions
            ) as response,
        ):
            return response.status_code, response.headers.get("content-type")
    except httpx.HTTPError:
        raise LlmProviderUnreachable from None
