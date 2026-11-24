import gzip
import json
import socket
import threading
import zlib
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
import pytest
from hamcrest import assert_that, equal_to, none

from api.domains.llm_providers.models import ProviderType
from api.infrastructure.llm_provider_catalogue.catalogue import (
    LlmProviderCatalogue,
    ProviderListBusy,
    ProviderListRefused,
    ProviderListUnreachable,
    ProviderListUnreadable,
)

API_KEY = "sk-provider-key-5678"
PUBLIC_ADDRESS = "8.8.8.8"
CUSTOM_BASE_URL = "https://models.example.com/v1"
RESOLVE = "api.infrastructure.public_http.socket.getaddrinfo"
HTTPX_CLIENT = "api.infrastructure.llm_provider_catalogue.catalogue.httpx.Client"
DNS_TIMEOUT = "api.infrastructure.llm_provider_catalogue.catalogue.DNS_TIMEOUT_SECONDS"
CLOCK = "api.infrastructure.llm_provider_catalogue.catalogue.time.monotonic"
REAL_HTTPX_CLIENT = httpx.Client
PROVIDER_LISTS = [
    (ProviderType.OPENAI, None, "https://api.openai.com/v1/models", "data"),
    (ProviderType.XAI, None, "https://api.x.ai/v1/language-models", "models"),
    (ProviderType.DEEPSEEK, None, "https://api.deepseek.com/models", "data"),
    (ProviderType.NOVITA, None, "https://api.novita.ai/openai/v1/models", "data"),
    (ProviderType.CUSTOM, CUSTOM_BASE_URL, "https://models.example.com/v1/models", "data"),
]
ANTHROPIC_URL = "https://api.anthropic.com/v1/models?limit=1000"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
FIREWORKS_URL = "https://api.fireworks.ai/v1/accounts/fireworks/models?filter=supports_serverless%3Dtrue&pageSize=200"
PAGED_LISTS = [
    (ProviderType.ANTHROPIC, ANTHROPIC_URL, {"x-api-key": API_KEY, "anthropic-version": "2026-10-21"}),
    (ProviderType.GEMINI, GEMINI_URL, {"x-goog-api-key": API_KEY}),
    (ProviderType.FIREWORKS, FIREWORKS_URL, {"Authorization": f"Bearer {API_KEY}"}),
]
GEMINI_METHODS = {"supportedGenerationMethods": ["generateContent"]}
FIREWORKS_CHAT = {"conversationConfig": {"style": "llama"}}
PROVIDERS = [(provider_type, base_url) for provider_type, base_url, _, _ in PROVIDER_LISTS] + [
    (provider_type, None) for provider_type, _, _ in PAGED_LISTS
]


def _listing(*ids: object, key: str = "data") -> bytes:
    return json.dumps({"object": "list", key: [{"id": model_id, "object": "model"} for model_id in ids]}).encode()


def _page(key: str, entries: list[dict], **cursor: object) -> bytes:
    return json.dumps({key: entries, **cursor}).encode()


class _Provider:
    def __init__(self, status_code=200, body=b"", headers=None, failure=None, pages=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {"Content-Type": "application/json"}
        self.failure = failure
        self.pages = pages
        self.requests: list[httpx.Request] = []
        self.client_settings: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        body = self.pages[len(self.requests) - 1] if self.pages is not None else self.body
        return httpx.Response(self.status_code, headers=self.headers, content=body)

    def client(self, **settings) -> httpx.Client:
        self.client_settings.append(settings)
        return REAL_HTTPX_CLIENT(**settings, transport=httpx.MockTransport(self))


@contextmanager
def _answering(provider: _Provider, address: str = PUBLIC_ADDRESS):
    rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with patch(RESOLVE, return_value=rows), patch(HTTPX_CLIENT, provider.client):
        yield


def _list(provider_type: ProviderType, base_url: str | None = None) -> list[str]:
    return LlmProviderCatalogue().list_models(provider_type, API_KEY, base_url)


def _requested_url(request: httpx.Request) -> str:
    return f"{request.url.scheme}://{request.headers['host']}{request.url.raw_path.decode()}"


@pytest.mark.parametrize(("provider_type", "base_url", "url", "key"), PROVIDER_LISTS)
def test_each_provider_is_asked_at_its_own_list_with_the_key(provider_type, base_url, url, key):
    provider = _Provider(body=_listing("model-b", "model-a", key=key))

    with _answering(provider):
        models = _list(provider_type, base_url)

    assert_that(models, equal_to(["model-a", "model-b"]))
    [request] = provider.requests
    assert_that(request.method, equal_to("GET"))
    assert_that(request.url.host, equal_to(PUBLIC_ADDRESS))
    assert_that(_requested_url(request), equal_to(url))
    assert_that(request.headers["Authorization"], equal_to(f"Bearer {API_KEY}"))


def test_a_trailing_slash_on_the_base_url_is_ignored():
    provider = _Provider(body=_listing("llama-3"))

    with _answering(provider):
        _list(ProviderType.CUSTOM, f"{CUSTOM_BASE_URL}/")

    assert_that(_requested_url(provider.requests[0]), equal_to("https://models.example.com/v1/models"))


def test_the_list_waits_ten_seconds_and_follows_no_redirect():
    provider = _Provider(body=_listing("gpt-4o"))

    with _answering(provider):
        _list(ProviderType.OPENAI)

    assert_that(provider.client_settings, equal_to([{"timeout": 10, "follow_redirects": False}]))


def test_ids_that_could_not_be_stored_are_left_out_and_each_id_is_kept_once():
    body = json.dumps(
        {
            "data": [
                {"id": "accounts/fireworks/models/llama-v3p1-8b"},
                {"id": "gpt-4o"},
                {"id": "gpt-4o"},
                {"id": "openai/*"},
                {"id": "has space"},
                {"id": "line\n"},
                {"id": ""},
                {"id": "m" * 201},
                {"id": 42},
                {"name": "no-id"},
                "not-an-object",
            ]
        }
    ).encode()

    with _answering(_Provider(body=body)):
        models = _list(ProviderType.OPENAI)

    assert_that(models, equal_to(["accounts/fireworks/models/llama-v3p1-8b", "gpt-4o"]))


def test_an_id_of_200_characters_is_kept():
    with _answering(_Provider(body=_listing("m" * 200))):
        assert_that(_list(ProviderType.OPENAI), equal_to(["m" * 200]))


def test_a_list_of_1000_entries_is_read():
    with _answering(_Provider(body=_listing(*(f"model-{index:04d}" for index in range(1000))))):
        assert_that(_list(ProviderType.OPENAI), equal_to([f"model-{index:04d}" for index in range(1000)]))


def test_a_list_of_more_than_1000_entries_is_unreadable():
    with _answering(_Provider(body=_listing(*(f"model-{index}" for index in range(1001))))):
        with pytest.raises(ProviderListUnreadable):
            _list(ProviderType.OPENAI)


def test_a_body_over_2_mib_is_unreadable():
    body = json.dumps({"data": [{"id": "gpt-4o", "padding": "x" * (2 * 1024 * 1024)}]}).encode()

    with _answering(_Provider(body=body)), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.OPENAI)


def test_a_small_compressed_body_that_decodes_over_2_mib_is_unreadable():
    body = gzip.compress(json.dumps({"data": [], "padding": " " * (3 * 1024 * 1024)}).encode())
    headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
    assert len(body) < 64 * 1024

    with _answering(_Provider(body=body, headers=headers)), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.OPENAI)


def test_the_list_is_asked_uncompressed():
    provider = _Provider(body=_listing("gpt-4o"))

    with _answering(provider):
        _list(ProviderType.OPENAI)

    assert_that(provider.requests[0].headers["Accept-Encoding"], equal_to("identity"))


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_a_compressed_list_is_unreadable_even_when_it_would_be_a_valid_list(encoding):
    headers = {"Content-Type": "application/json", "Content-Encoding": encoding}
    body = gzip.compress(_listing("gpt-4o")) if encoding == "gzip" else zlib.compress(_listing("gpt-4o"))

    with _answering(_Provider(body=body, headers=headers)), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.OPENAI)


def test_a_list_still_arriving_after_30_seconds_is_unreachable():
    started, late = 1000.0, 1000.0 + 31

    with (
        _answering(_Provider(body=_listing("gpt-4o"))),
        patch(CLOCK, side_effect=[started, started, late]),
        pytest.raises(ProviderListUnreachable),
    ):
        _list(ProviderType.OPENAI)


def test_a_next_page_is_not_asked_after_30_seconds():
    started, late = 1000.0, 1000.0 + 31
    first = _page("data", [{"id": "claude-a"}], has_more=True, last_id="claude-a")
    provider = _Provider(pages=[first, _page("data", [{"id": "claude-b"}], has_more=False)])

    with (
        _answering(provider),
        patch(CLOCK, side_effect=[started, started, started, late]),
        pytest.raises(ProviderListUnreachable),
    ):
        _list(ProviderType.ANTHROPIC)

    assert_that(len(provider.requests), equal_to(1))


@pytest.mark.parametrize(
    "body",
    [b"<html>not json</html>", b"[]", b'{"models": []}', b'{"data": {"id": "gpt-4o"}}', b'"data"'],
)
def test_a_body_that_is_not_a_model_list_is_unreadable(body):
    with _answering(_Provider(body=body)), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.OPENAI)


def test_xai_lists_under_models_not_data():
    with _answering(_Provider(body=_listing("grok-4", key="data"))), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.XAI)


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.parametrize(("provider_type", "base_url"), PROVIDERS)
def test_a_key_the_provider_refuses_is_refused(provider_type, base_url, status_code):
    with _answering(_Provider(status_code)), pytest.raises(ProviderListRefused):
        _list(provider_type, base_url)


@pytest.mark.parametrize("provider_type", [ProviderType.XAI, ProviderType.GEMINI])
def test_xai_and_gemini_refuse_an_invalid_key_with_400(provider_type):
    with _answering(_Provider(400)), pytest.raises(ProviderListRefused):
        _list(provider_type)


@pytest.mark.parametrize("status_code", [400, 404, 500])
def test_any_other_anthropic_answer_is_unreachable(status_code):
    with _answering(_Provider(status_code)), pytest.raises(ProviderListUnreachable):
        _list(ProviderType.ANTHROPIC)


@pytest.mark.parametrize(("provider_type", "base_url"), PROVIDERS)
def test_a_provider_limiting_requests_is_busy(provider_type, base_url):
    with _answering(_Provider(429)), pytest.raises(ProviderListBusy):
        _list(provider_type, base_url)


@pytest.mark.parametrize("status_code", [400, 404, 500, 503])
def test_an_answer_that_is_not_a_list_or_a_refusal_is_unreachable(status_code):
    with _answering(_Provider(status_code)), pytest.raises(ProviderListUnreachable):
        _list(ProviderType.OPENAI)


def test_a_redirect_is_not_followed():
    provider = _Provider(302, headers={"Location": "https://elsewhere.example.com/models"})

    with _answering(provider), pytest.raises(ProviderListUnreachable):
        _list(ProviderType.CUSTOM, CUSTOM_BASE_URL)

    assert_that(len(provider.requests), equal_to(1))


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError(f"connection failed for {API_KEY}"), httpx.ReadTimeout(f"timed out for {API_KEY}")],
)
def test_no_answer_is_unreachable_without_the_key(failure):
    with _answering(_Provider(failure=failure)), pytest.raises(ProviderListUnreachable) as raised:
        _list(ProviderType.OPENAI)

    assert_that(API_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__, none())
    assert_that(raised.value.__suppress_context__, equal_to(True))


@pytest.mark.parametrize(
    ("provider", "error"),
    [
        (_Provider(401, body=json.dumps({"error": f"bad key {API_KEY}"}).encode()), ProviderListRefused),
        (_Provider(500, body=API_KEY.encode()), ProviderListUnreachable),
        (_Provider(body=f"not json {API_KEY}".encode()), ProviderListUnreadable),
    ],
)
def test_no_error_carries_the_key(provider, error):
    with _answering(provider), pytest.raises(error) as raised:
        _list(ProviderType.OPENAI)

    assert_that(API_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__, none())


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "169.254.169.254"])
def test_a_private_address_is_unreachable_before_any_request(address):
    provider = _Provider(body=_listing("llama-3"))

    with _answering(provider, address), pytest.raises(ProviderListUnreachable):
        _list(ProviderType.CUSTOM, CUSTOM_BASE_URL)

    assert_that(provider.requests, equal_to([]))


def test_a_name_that_does_not_resolve_is_unreachable():
    with patch(RESOLVE, side_effect=socket.gaierror), pytest.raises(ProviderListUnreachable):
        _list(ProviderType.DEEPSEEK)


def test_a_dns_lookup_that_hangs_is_unreachable_without_waiting_for_it():
    released = threading.Event()

    def hang(*_, **__):
        released.wait(5)
        raise socket.gaierror

    provider = _Provider(body=_listing("gpt-4o"))
    try:
        with (
            patch(RESOLVE, side_effect=hang),
            patch(HTTPX_CLIENT, provider.client),
            patch(DNS_TIMEOUT, 0.05),
            pytest.raises(ProviderListUnreachable),
        ):
            _list(ProviderType.OPENAI)
    finally:
        released.set()

    assert_that(provider.requests, equal_to([]))


@pytest.mark.parametrize(
    ("provider_type", "base_url"),
    [
        (ProviderType.AZURE, "https://contoso.openai.azure.com"),
        (ProviderType.AZURE, None),
        (ProviderType.ANTHROPIC, CUSTOM_BASE_URL),
        (ProviderType.OPENROUTER, None),
        (ProviderType.CUSTOM, None),
        (ProviderType.OPENAI, CUSTOM_BASE_URL),
    ],
)
def test_a_list_the_catalogue_does_not_read_is_a_programming_error(provider_type, base_url):
    provider = _Provider(body=_listing("gpt-4o"))

    with _answering(provider), pytest.raises(ValueError):
        _list(provider_type, base_url)

    assert_that(provider.requests, equal_to([]))


@pytest.mark.parametrize(("provider_type", "url", "auth_headers"), PAGED_LISTS)
def test_each_paged_provider_is_asked_for_its_largest_page_with_its_key(provider_type, url, auth_headers):
    provider = _Provider(body=b'{"data": [], "models": [], "has_more": false}')

    with _answering(provider):
        _list(provider_type)

    [request] = provider.requests
    assert_that(request.url.host, equal_to(PUBLIC_ADDRESS))
    assert_that(_requested_url(request), equal_to(url))
    for name, value in auth_headers.items():
        assert_that(request.headers[name], equal_to(value))
    if "Authorization" not in auth_headers:
        assert_that(request.headers.get("Authorization"), none())


def test_anthropic_lists_every_model_it_returns():
    body = _page("data", [{"id": "claude-sonnet-4-5"}, {"id": "claude-opus-5-5"}], has_more=False)

    with _answering(_Provider(body=body)):
        assert_that(_list(ProviderType.ANTHROPIC), equal_to(["claude-opus-5-5", "claude-sonnet-4-5"]))


def test_gemini_lists_only_models_that_generate_content_without_their_prefix():
    body = _page(
        "models",
        [
            {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent", "countTokens"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/no-methods"},
            {"name": "tunedModels/my-model", "supportedGenerationMethods": ["generateContent"]},
            {"supportedGenerationMethods": ["generateContent"]},
        ],
    )

    with _answering(_Provider(body=body)):
        assert_that(_list(ProviderType.GEMINI), equal_to(["gemini-2.5-pro"]))


def test_fireworks_lists_only_models_with_a_chat_template_by_their_full_name():
    body = _page(
        "models",
        [
            {"name": "accounts/fireworks/models/llama-v3p1-8b-instruct", "conversationConfig": {"style": "llama"}},
            {"name": "accounts/fireworks/models/nomic-embed-text-v1p5", "kind": "EMBEDDING_MODEL"},
            {"name": "accounts/fireworks/models/broken", "conversationConfig": "chat"},
        ],
    )

    with _answering(_Provider(body=body)):
        assert_that(_list(ProviderType.FIREWORKS), equal_to(["accounts/fireworks/models/llama-v3p1-8b-instruct"]))


@pytest.mark.parametrize(
    ("provider_type", "first", "second", "next_url", "models"),
    [
        (
            ProviderType.ANTHROPIC,
            _page("data", [{"id": "claude-b"}], has_more=True, last_id="claude-b"),
            _page("data", [{"id": "claude-a"}], has_more=False, last_id="claude-a"),
            f"{ANTHROPIC_URL}&after_id=claude-b",
            ["claude-a", "claude-b"],
        ),
        (
            ProviderType.GEMINI,
            _page("models", [{"name": "models/gemini-b", **GEMINI_METHODS}], nextPageToken="page/2=="),
            _page("models", [{"name": "models/gemini-a", **GEMINI_METHODS}]),
            f"{GEMINI_URL}&pageToken=page%2F2%3D%3D",
            ["gemini-a", "gemini-b"],
        ),
        (
            ProviderType.FIREWORKS,
            _page("models", [{"name": "accounts/fireworks/models/b", **FIREWORKS_CHAT}], nextPageToken="tok-2"),
            _page("models", [{"name": "accounts/fireworks/models/a", **FIREWORKS_CHAT}], nextPageToken=""),
            f"{FIREWORKS_URL}&pageToken=tok-2",
            ["accounts/fireworks/models/a", "accounts/fireworks/models/b"],
        ),
    ],
)
def test_the_next_page_is_asked_with_the_cursor_until_the_last(provider_type, first, second, next_url, models):
    provider = _Provider(pages=[first, second])

    with _answering(provider):
        listed = _list(provider_type)

    assert_that(listed, equal_to(models))
    assert_that([_requested_url(request) for request in provider.requests][1:], equal_to([next_url]))


def test_a_listing_is_resolved_once_for_all_its_pages():
    rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_ADDRESS, 443))]
    resolve = Mock(return_value=rows)
    pages = [_page("data", [{"id": f"claude-{index}"}], has_more=True, last_id=f"claude-{index}") for index in range(2)]
    provider = _Provider(pages=[*pages, _page("data", [], has_more=False)])

    with patch(RESOLVE, resolve), patch(HTTPX_CLIENT, provider.client):
        _list(ProviderType.ANTHROPIC)

    assert_that(len(provider.requests), equal_to(3))
    assert_that(resolve.call_count, equal_to(1))


def test_more_than_five_pages_is_unreadable():
    pages = [_page("models", [], nextPageToken=f"tok-{index}") for index in range(6)]
    provider = _Provider(pages=pages)

    with _answering(provider), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.FIREWORKS)

    assert_that(len(provider.requests), equal_to(5))


def test_five_pages_are_read():
    pages = [_page("models", [], nextPageToken=f"tok-{index}") for index in range(4)] + [_page("models", [])]

    with _answering(_Provider(pages=pages)):
        assert_that(_list(ProviderType.FIREWORKS), equal_to([]))


def test_more_than_1000_entries_across_pages_is_unreadable():
    first = _page("models", [{"name": f"models/m-{index}"} for index in range(600)], nextPageToken="tok-2")
    second = _page("models", [{"name": f"models/n-{index}"} for index in range(401)])

    with _answering(_Provider(pages=[first, second])), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.GEMINI)


@pytest.mark.parametrize(
    ("provider_type", "body"),
    [
        (ProviderType.ANTHROPIC, _page("data", [], has_more=True)),
        (ProviderType.ANTHROPIC, _page("data", [], has_more=True, last_id=None)),
        (ProviderType.GEMINI, _page("models", [], nextPageToken=42)),
        (ProviderType.FIREWORKS, _page("data", [{"name": "accounts/fireworks/models/a", **FIREWORKS_CHAT}])),
    ],
)
def test_a_page_without_a_usable_cursor_or_list_is_unreadable(provider_type, body):
    with _answering(_Provider(body=body)), pytest.raises(ProviderListUnreadable):
        _list(provider_type)


def test_a_failure_on_a_later_page_fails_the_listing():
    first = _page("data", [{"id": "claude-a"}], has_more=True, last_id="claude-a")

    with _answering(_Provider(pages=[first, b"not json"])), pytest.raises(ProviderListUnreadable):
        _list(ProviderType.ANTHROPIC)
