import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as LookupTimeout
from dataclasses import dataclass

import httpx
from injector import singleton

from api.domains.llm_providers.models import MAX_MODEL_ID_LENGTH, MODEL_ID_PATTERN, ProviderType
from api.infrastructure.public_http import NonPublicDestination, PinnedRequest, pin_to_public_address

TIMEOUT_SECONDS = 10
DNS_TIMEOUT_SECONDS = 5
DNS_WORKERS = 4
MAX_LIST_BYTES = 2 * 1024 * 1024
MAX_LIST_ENTRIES = 1000
REFUSED_MESSAGE = "The provider did not accept the stored key"
UNREACHABLE_MESSAGE = "The provider could not be reached to list its models"
UNREADABLE_MESSAGE = "The provider's model list could not be read"
REFUSED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


@dataclass(frozen=True)
class _Endpoint:
    url: str
    list_key: str = "data"


_ENDPOINTS = {
    ProviderType.OPENAI: _Endpoint("https://api.openai.com/v1/models"),
    ProviderType.XAI: _Endpoint("https://api.x.ai/v1/language-models", "models"),
    ProviderType.DEEPSEEK: _Endpoint("https://api.deepseek.com/models"),
    ProviderType.NOVITA: _Endpoint("https://api.novita.ai/openai/v1/models"),
    ProviderType.CUSTOM: _Endpoint("/models"),
}
_EXTRA_REFUSED_STATUSES = {ProviderType.XAI: frozenset({httpx.codes.BAD_REQUEST})}


class ProviderListError(Exception):
    """The provider's model list could not be had. The message is fixed and never carries the key."""


class ProviderListRefused(ProviderListError):
    def __init__(self) -> None:
        super().__init__(REFUSED_MESSAGE)


class ProviderListUnreachable(ProviderListError):
    def __init__(self) -> None:
        super().__init__(UNREACHABLE_MESSAGE)


class ProviderListUnreadable(ProviderListError):
    def __init__(self) -> None:
        super().__init__(UNREADABLE_MESSAGE)


def _storable(model_id: object) -> bool:
    return (
        isinstance(model_id, str)
        and len(model_id) <= MAX_MODEL_ID_LENGTH
        and re.fullmatch(MODEL_ID_PATTERN, model_id) is not None
    )


def _model_ids(body: bytes, list_key: str) -> list[str]:
    try:
        document = json.loads(body)
    except ValueError:
        raise ProviderListUnreadable from None
    entries = document.get(list_key) if isinstance(document, dict) else None
    if not isinstance(entries, list) or len(entries) > MAX_LIST_ENTRIES:
        raise ProviderListUnreadable
    return sorted({entry["id"] for entry in entries if isinstance(entry, dict) and _storable(entry.get("id"))})


def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_LIST_BYTES:
            raise ProviderListUnreadable
    return bytes(body)


@singleton
class LlmProviderCatalogue:
    def __init__(self) -> None:
        self._lookups = ThreadPoolExecutor(max_workers=DNS_WORKERS, thread_name_prefix="llm-provider-dns")

    def list_models(self, provider_type: ProviderType, api_key: str, base_url: str | None = None) -> list[str]:
        """The ids the provider lists for this key that a model row can hold, sorted and each once.

        Raises ``ProviderListRefused`` when the provider refuses the key, ``ProviderListUnreachable``
        when it gives no list, and ``ProviderListUnreadable`` when its answer is not a model list or
        is over the size or entry cap.
        """
        endpoint = _ENDPOINTS.get(provider_type)
        if endpoint is None:
            raise ValueError(f"{provider_type} models are not listed by LlmProviderCatalogue")
        if (provider_type is ProviderType.CUSTOM) != (base_url is not None):
            raise ValueError("Only Custom connections are listed at a base URL, and they must be")

        url = f"{base_url.rstrip('/')}{endpoint.url}" if base_url is not None else endpoint.url
        pinned = self._pin(url)
        headers = {**pinned.headers, "Authorization": f"Bearer {api_key}"}
        try:
            with (
                httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
                client.stream("GET", pinned.url, headers=headers, extensions=pinned.extensions) as response,
            ):
                status_code = response.status_code
                body = _read_capped(response) if status_code == httpx.codes.OK else b""
        except httpx.HTTPError:
            raise ProviderListUnreachable from None

        if status_code == httpx.codes.OK:
            return _model_ids(body, endpoint.list_key)
        if status_code in REFUSED_STATUSES | _EXTRA_REFUSED_STATUSES.get(provider_type, frozenset()):
            raise ProviderListRefused
        raise ProviderListUnreachable

    def _pin(self, url: str) -> PinnedRequest:
        lookup = self._lookups.submit(pin_to_public_address, url)
        try:
            return lookup.result(timeout=DNS_TIMEOUT_SECONDS)
        except NonPublicDestination, LookupTimeout:
            raise ProviderListUnreachable from None
