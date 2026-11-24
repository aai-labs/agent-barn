import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as LookupTimeout
from dataclasses import dataclass
from typing import TypeIs

import httpx
from injector import singleton

from api.domains.llm_providers.models import MAX_MODEL_ID_LENGTH, MODEL_ID_PATTERN, ProviderType
from api.infrastructure.public_http import NonPublicDestination, PinnedRequest, pin_to_public_address

TIMEOUT_SECONDS = 10
LIST_DEADLINE_SECONDS = 30
DNS_TIMEOUT_SECONDS = 5
DNS_WORKERS = 4
MAX_LIST_BYTES = 2 * 1024 * 1024
MAX_LIST_ENTRIES = 1000
MAX_LIST_PAGES = 5
ANTHROPIC_VERSION = "2026-10-21"
GEMINI_MODEL_PREFIX = "models/"
GEMINI_CHAT_METHOD = "generateContent"
REFUSED_MESSAGE = "The provider did not accept the stored key"
UNREACHABLE_MESSAGE = "The provider could not be reached to list its models"
UNREADABLE_MESSAGE = "The provider's model list could not be read"
BUSY_MESSAGE = "The provider is limiting requests"
IDENTITY = "identity"
REFUSED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


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


class ProviderListBusy(ProviderListError):
    def __init__(self) -> None:
        super().__init__(BUSY_MESSAGE)


def _entry_id(entry: dict) -> object:
    return entry.get("id")


def _gemini_id(entry: dict) -> object:
    name = entry.get("name")
    methods = entry.get("supportedGenerationMethods")
    if not isinstance(name, str) or not name.startswith(GEMINI_MODEL_PREFIX) or not isinstance(methods, list):
        return None
    return name.removeprefix(GEMINI_MODEL_PREFIX) if GEMINI_CHAT_METHOD in methods else None


def _fireworks_id(entry: dict) -> object:
    return entry.get("name") if isinstance(entry.get("conversationConfig"), dict) else None


def _single_page(_: dict) -> tuple[str, str] | None:
    return None


def _anthropic_next_page(document: dict) -> tuple[str, str] | None:
    if document.get("has_more") is not True:
        return None
    last_id = document.get("last_id")
    if not isinstance(last_id, str) or not last_id:
        raise ProviderListUnreadable
    return ("after_id", last_id)


def _next_page_token(document: dict) -> tuple[str, str] | None:
    token = document.get("nextPageToken")
    if token is None or token == "":
        return None
    if not isinstance(token, str):
        raise ProviderListUnreadable
    return ("pageToken", token)


@dataclass(frozen=True)
class _Endpoint:
    url: str
    list_key: str = "data"
    key_header: str = "Authorization"
    key_prefix: str = "Bearer "
    headers: tuple[tuple[str, str], ...] = ()
    params: tuple[tuple[str, str], ...] = ()
    model_id: Callable[[dict], object] = _entry_id
    next_page: Callable[[dict], tuple[str, str] | None] = _single_page


_ENDPOINTS = {
    ProviderType.OPENAI: _Endpoint("https://api.openai.com/v1/models"),
    ProviderType.XAI: _Endpoint("https://api.x.ai/v1/language-models", "models"),
    ProviderType.DEEPSEEK: _Endpoint("https://api.deepseek.com/models"),
    ProviderType.NOVITA: _Endpoint("https://api.novita.ai/openai/v1/models"),
    ProviderType.CUSTOM: _Endpoint("/models"),
    ProviderType.ANTHROPIC: _Endpoint(
        "https://api.anthropic.com/v1/models",
        key_header="x-api-key",
        key_prefix="",
        headers=(("anthropic-version", ANTHROPIC_VERSION),),
        params=(("limit", "1000"),),
        next_page=_anthropic_next_page,
    ),
    ProviderType.GEMINI: _Endpoint(
        "https://generativelanguage.googleapis.com/v1beta/models",
        "models",
        key_header="x-goog-api-key",
        key_prefix="",
        params=(("pageSize", "1000"),),
        model_id=_gemini_id,
        next_page=_next_page_token,
    ),
    ProviderType.FIREWORKS: _Endpoint(
        "https://api.fireworks.ai/v1/accounts/fireworks/models",
        "models",
        params=(("filter", "supports_serverless=true"), ("pageSize", "200")),
        model_id=_fireworks_id,
        next_page=_next_page_token,
    ),
}
_EXTRA_REFUSED_STATUSES = {
    ProviderType.GEMINI: frozenset({httpx.codes.BAD_REQUEST}),
    ProviderType.XAI: frozenset({httpx.codes.BAD_REQUEST}),
}


def _storable(model_id: object) -> TypeIs[str]:
    return (
        isinstance(model_id, str)
        and len(model_id) <= MAX_MODEL_ID_LENGTH
        and re.fullmatch(MODEL_ID_PATTERN, model_id) is not None
    )


def _document(body: bytes) -> dict:
    try:
        document = json.loads(body)
    except ValueError:
        raise ProviderListUnreadable from None
    if not isinstance(document, dict):
        raise ProviderListUnreadable
    return document


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ProviderListUnreachable


def _read_capped(response: httpx.Response, deadline: float) -> bytes:
    """The body as sent, refused when it is compressed, over the byte cap, or still arriving at the
    deadline. A compressed body is refused rather than inflated, since a small one can inflate to
    far more than the cap before the cap is checked."""
    if response.headers.get("Content-Encoding", IDENTITY).strip().lower() != IDENTITY:
        raise ProviderListUnreadable
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_LIST_BYTES:
            raise ProviderListUnreadable
        _check_deadline(deadline)
    return bytes(body)


@singleton
class LlmProviderCatalogue:
    def __init__(self) -> None:
        self._lookups = ThreadPoolExecutor(max_workers=DNS_WORKERS, thread_name_prefix="llm-provider-dns")

    def list_models(self, provider_type: ProviderType, api_key: str, base_url: str | None = None) -> list[str]:
        """The ids the provider lists for this key that a model row can hold, sorted and each once.

        Raises ``ProviderListRefused`` when the provider refuses the key, ``ProviderListBusy`` when
        it is limiting requests, ``ProviderListUnreachable`` when it gives no list or not all of it
        within ``LIST_DEADLINE_SECONDS``, and ``ProviderListUnreadable`` when its answer is not a
        model list, is compressed, or is over the size, entry or page cap.
        """
        endpoint = _ENDPOINTS.get(provider_type)
        if endpoint is None:
            raise ValueError(f"{provider_type} models are not listed by LlmProviderCatalogue")
        if (provider_type is ProviderType.CUSTOM) != (base_url is not None):
            raise ValueError("Only Custom connections are listed at a base URL, and they must be")

        url = f"{base_url.rstrip('/')}{endpoint.url}" if base_url is not None else endpoint.url
        pinned = self._pin(url)
        headers = {
            **pinned.headers,
            **dict(endpoint.headers),
            endpoint.key_header: f"{endpoint.key_prefix}{api_key}",
            "Accept-Encoding": IDENTITY,
        }
        refused = REFUSED_STATUSES | _EXTRA_REFUSED_STATUSES.get(provider_type, frozenset())
        model_ids: set[str] = set()
        entry_count = 0
        cursor: tuple[str, str] | None = None
        deadline = time.monotonic() + LIST_DEADLINE_SECONDS
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                for _ in range(MAX_LIST_PAGES):
                    params = endpoint.params if cursor is None else (*endpoint.params, cursor)
                    _check_deadline(deadline)
                    document = self._page(client, pinned, headers, params, refused, deadline)
                    entries = document.get(endpoint.list_key)
                    if not isinstance(entries, list):
                        raise ProviderListUnreadable
                    entry_count += len(entries)
                    if entry_count > MAX_LIST_ENTRIES:
                        raise ProviderListUnreadable
                    model_ids |= {
                        model_id
                        for entry in entries
                        if isinstance(entry, dict) and _storable(model_id := endpoint.model_id(entry))
                    }
                    cursor = endpoint.next_page(document)
                    if cursor is None:
                        return sorted(model_ids)
        except httpx.HTTPError:
            raise ProviderListUnreachable from None
        raise ProviderListUnreadable

    @staticmethod
    def _page(
        client: httpx.Client,
        pinned: PinnedRequest,
        headers: dict[str, str],
        params: tuple[tuple[str, str], ...],
        refused: frozenset[int],
        deadline: float,
    ) -> dict:
        with client.stream("GET", pinned.url, params=params, headers=headers, extensions=pinned.extensions) as response:
            if response.status_code == httpx.codes.OK:
                return _document(_read_capped(response, deadline))
            if response.status_code in refused:
                raise ProviderListRefused
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise ProviderListBusy
            raise ProviderListUnreachable

    def _pin(self, url: str) -> PinnedRequest:
        lookup = self._lookups.submit(pin_to_public_address, url)
        try:
            return lookup.result(timeout=DNS_TIMEOUT_SECONDS)
        except NonPublicDestination, LookupTimeout:
            raise ProviderListUnreachable from None
