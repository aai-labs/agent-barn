"""Checking an LLM provider's key with the provider before it is stored."""

import socket
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from hamcrest import assert_that, equal_to, none

from api.domains.llm_providers.models import ProviderType
from api.infrastructure.llm_provider_keys.checker import (
    BaseUrlNotAnApi,
    BaseUrlNotPublic,
    LlmProviderKeyChecker,
    LlmProviderUnreachable,
)

CANDIDATE_KEY = "sk-candidate-key-1234"
PUBLIC_ADDRESS = "8.8.8.8"
CUSTOM_BASE_URL = "https://models.example.com/v1"
AZURE_BASE_URL = "https://contoso.openai.azure.com"
RESOLVE = "api.infrastructure.public_http.socket.getaddrinfo"
HTTPX_CLIENT = "api.infrastructure.llm_provider_keys.checker.httpx.Client"
BEARER = {"Authorization": f"Bearer {CANDIDATE_KEY}"}
REAL_HTTPX_CLIENT = httpx.Client
JSON = {"Content-Type": "application/json"}

PROVIDER_REQUESTS = [
    (
        ProviderType.ANTHROPIC,
        None,
        "https://api.anthropic.com/v1/models",
        {"x-api-key": CANDIDATE_KEY, "anthropic-version": "2026-10-21"},
    ),
    (ProviderType.OPENAI, None, "https://api.openai.com/v1/models", BEARER),
    (
        ProviderType.GEMINI,
        None,
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": CANDIDATE_KEY},
    ),
    (ProviderType.XAI, None, "https://api.x.ai/v1/models", BEARER),
    (ProviderType.DEEPSEEK, None, "https://api.deepseek.com/models", BEARER),
    (ProviderType.FIREWORKS, None, "https://api.fireworks.ai/v1/accounts", BEARER),
    (ProviderType.NOVITA, None, "https://api.novita.ai/v3/user", BEARER),
    (
        ProviderType.AZURE,
        AZURE_BASE_URL,
        "https://contoso.openai.azure.com/openai/v1/models",
        {"api-key": CANDIDATE_KEY},
    ),
    (ProviderType.CUSTOM, CUSTOM_BASE_URL, "https://models.example.com/v1/models", BEARER),
]
PROVIDERS = [(provider_type, base_url) for provider_type, base_url, _, _ in PROVIDER_REQUESTS]


class _Provider:
    def __init__(self, status_code=200, headers=JSON, failure=None, stream=None):
        self.status_code = status_code
        self.headers = headers
        self.failure = failure
        self.stream = stream
        self.requests: list[httpx.Request] = []
        self.client_settings: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return httpx.Response(self.status_code, headers=self.headers, stream=self.stream)

    def client(self, **settings) -> httpx.Client:
        self.client_settings.append(settings)
        return REAL_HTTPX_CLIENT(**settings, transport=httpx.MockTransport(self))


class _UnreadableBody(httpx.SyncByteStream):
    def __iter__(self):
        raise AssertionError("the response body was read")


@contextmanager
def _answering(provider: _Provider, address: str = PUBLIC_ADDRESS):
    rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with patch(RESOLVE, return_value=rows), patch(HTTPX_CLIENT, provider.client):
        yield


def _check(provider_type: ProviderType, base_url: str | None) -> bool:
    return LlmProviderKeyChecker().check(provider_type, CANDIDATE_KEY, base_url)


def _requested_url(request: httpx.Request) -> str:
    return f"{request.url.scheme}://{request.headers['host']}{request.url.raw_path.decode()}"


@pytest.mark.parametrize(("provider_type", "base_url", "url", "auth_headers"), PROVIDER_REQUESTS)
def test_each_provider_is_asked_at_its_documented_endpoint(provider_type, base_url, url, auth_headers):
    provider = _Provider(200)

    with _answering(provider):
        accepted = _check(provider_type, base_url)

    assert_that(accepted, equal_to(True))
    assert_that(len(provider.requests), equal_to(1))
    request = provider.requests[0]
    assert_that(request.method, equal_to("GET"))
    assert_that(request.url.host, equal_to(PUBLIC_ADDRESS))
    assert_that(_requested_url(request), equal_to(url))
    for name, value in auth_headers.items():
        assert_that(request.headers[name], equal_to(value))


def test_a_trailing_slash_on_the_base_url_is_ignored():
    provider = _Provider(200)

    with _answering(provider):
        _check(ProviderType.CUSTOM, f"{CUSTOM_BASE_URL}/")

    assert_that(_requested_url(provider.requests[0]), equal_to("https://models.example.com/v1/models"))


def test_the_check_waits_ten_seconds_and_follows_no_redirect():
    provider = _Provider(200)

    with _answering(provider):
        _check(ProviderType.OPENAI, None)

    assert_that(provider.client_settings, equal_to([{"timeout": 10, "follow_redirects": False}]))


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.parametrize(("provider_type", "base_url"), PROVIDERS)
def test_a_key_the_provider_refuses_does_not_check_out(provider_type, base_url, status_code):
    with _answering(_Provider(status_code)):
        assert_that(_check(provider_type, base_url), equal_to(False))


def test_gemini_refuses_an_invalid_key_with_400():
    with _answering(_Provider(400)):
        assert_that(_check(ProviderType.GEMINI, None), equal_to(False))


def test_xai_refuses_an_invalid_key_with_400():
    with _answering(_Provider(400)):
        assert_that(_check(ProviderType.XAI, None), equal_to(False))


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 502, 503])
def test_an_answer_that_settles_nothing_is_unreachable_without_the_key(status_code):
    with _answering(_Provider(status_code)), pytest.raises(LlmProviderUnreachable) as raised:
        _check(ProviderType.OPENAI, None)

    assert_that(CANDIDATE_KEY in str(raised.value), equal_to(False))


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError(f"connection failed for {CANDIDATE_KEY}"),
        httpx.ReadTimeout(f"timed out for {CANDIDATE_KEY}"),
    ],
)
def test_no_answer_is_unreachable_without_the_key(failure):
    with _answering(_Provider(failure=failure)), pytest.raises(LlmProviderUnreachable) as raised:
        _check(ProviderType.ANTHROPIC, None)

    assert_that(CANDIDATE_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__, none())
    assert_that(raised.value.__suppress_context__, equal_to(True))


@pytest.mark.parametrize(
    ("provider_type", "base_url", "error"),
    [
        (ProviderType.OPENAI, None, LlmProviderUnreachable),
        (ProviderType.AZURE, AZURE_BASE_URL, BaseUrlNotAnApi),
        (ProviderType.CUSTOM, CUSTOM_BASE_URL, BaseUrlNotAnApi),
    ],
)
def test_a_redirect_is_not_followed(provider_type, base_url, error):
    provider = _Provider(302, headers={"Location": "https://elsewhere.example.com/models"})

    with _answering(provider), pytest.raises(error):
        _check(provider_type, base_url)

    assert_that(len(provider.requests), equal_to(1))


@pytest.mark.parametrize("provider_type", [ProviderType.AZURE, ProviderType.CUSTOM])
@pytest.mark.parametrize(
    ("status_code", "headers"),
    [(200, {"Content-Type": "text/html; charset=utf-8"}), (200, {}), (404, JSON)],
)
def test_a_base_url_that_does_not_answer_like_an_api_is_refused(provider_type, status_code, headers):
    with _answering(_Provider(status_code, headers=headers)), pytest.raises(BaseUrlNotAnApi) as raised:
        _check(provider_type, CUSTOM_BASE_URL)

    assert_that(CANDIDATE_KEY in str(raised.value), equal_to(False))


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "application/problem+json"])
def test_a_json_answer_from_a_base_url_accepts_the_key(content_type):
    with _answering(_Provider(200, headers={"Content-Type": content_type})):
        assert_that(_check(ProviderType.CUSTOM, CUSTOM_BASE_URL), equal_to(True))


def test_a_known_provider_is_not_judged_by_its_content_type():
    with _answering(_Provider(200, headers={"Content-Type": "text/html"})):
        assert_that(_check(ProviderType.OPENAI, None), equal_to(True))


def test_the_response_body_is_never_read():
    with _answering(_Provider(200, stream=_UnreadableBody())):
        assert_that(_check(ProviderType.OPENAI, None), equal_to(True))


@pytest.mark.parametrize("provider_type", [ProviderType.AZURE, ProviderType.CUSTOM])
@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "169.254.169.254"])
def test_a_base_url_at_a_private_address_is_refused_before_any_request(provider_type, address):
    provider = _Provider(200)

    with _answering(provider, address), pytest.raises(BaseUrlNotPublic):
        _check(provider_type, CUSTOM_BASE_URL)

    assert_that(provider.requests, equal_to([]))


def test_a_base_url_that_is_not_https_is_refused_before_any_request():
    provider = _Provider(200)

    with _answering(provider), pytest.raises(BaseUrlNotPublic):
        _check(ProviderType.CUSTOM, "http://models.example.com/v1")

    assert_that(provider.requests, equal_to([]))


def test_a_known_provider_that_does_not_resolve_is_unreachable():
    with patch(RESOLVE, side_effect=socket.gaierror), pytest.raises(LlmProviderUnreachable):
        _check(ProviderType.DEEPSEEK, None)


@pytest.mark.parametrize(
    ("provider_type", "base_url"),
    [
        (ProviderType.OPENROUTER, None),  # OpenRouterClient.check_key checks OpenRouter keys
        (ProviderType.AZURE, None),
        (ProviderType.CUSTOM, None),
        (ProviderType.OPENAI, CUSTOM_BASE_URL),
    ],
)
def test_a_check_the_checker_does_not_make_is_a_programming_error(provider_type, base_url):
    provider = _Provider(200)

    with _answering(provider), pytest.raises(ValueError):
        _check(provider_type, base_url)

    assert_that(provider.requests, equal_to([]))
