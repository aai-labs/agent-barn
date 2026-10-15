import socket

import pytest

from api.domains.custom_api.request import RequestRefused, check_scope, credential_headers, public_addresses


@pytest.mark.parametrize(
    "url",
    [
        "/v1/items",
        "http://api.example.com/v1",
        "https://api.example.com.evil.test/v1",
        "https://api.example.com/v10",
        "https://api.example.com/v1/../admin",
        "https://api.example.com/v1/%2e%2e/admin",
        "https://api.example.com/v1//admin",
        "https://user@api.example.com/v1",
        "https://api.example.com:8443/v1",
        "https://api.example.com/v1\\admin",
        "https://api.example.com./v1",
        "https://api.example.com/v1/%FF",
    ],
)
def test_refuses_scope_escapes(url):
    with pytest.raises(RequestRefused):
        check_scope("https://api.example.com/v1", url)


def test_accepts_full_urls_inside_scope():
    check_scope("https://api.example.com/v1/", "https://api.example.com/v1/items?q=x")


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "224.0.0.1"])
def test_refuses_internal_dns(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(0, 0, 0, "", (address, 443))])
    with pytest.raises(RequestRefused):
        public_addresses("api.example.com")


def test_rejects_case_insensitive_duplicate_credentials():
    with pytest.raises(RequestRefused):
        credential_headers(
            {
                "auth": {"type": "api_key", "header_name": "X-Key", "token": "fixture"},
                "headers": [{"name": "x-key", "value": "override"}],
            }
        )


def test_accepts_encoded_names_without_allowing_encoded_scope_escape():
    check_scope("https://api.example.com/v1", "https://api.example.com/v1/hello%20world")
    for path in ["%252e%252e/admin", "name%2fadmin", "name%5cadmin", "%00item"]:
        with pytest.raises(RequestRefused):
            check_scope("https://api.example.com/v1", "https://api.example.com/v1/" + path)


def test_custom_authorization_header_is_configurable():
    from hamcrest import assert_that, has_entry

    headers, _ = credential_headers(
        {"auth": {"type": "api_key", "header_name": "Authorization", "token": "Token fixture"}}
    )
    assert_that(headers, has_entry("authorization", "Token fixture"))


@pytest.mark.parametrize("secret", ['quoted"token', "back\\slash", "123456789", "true", "null"])
def test_redacts_decoded_json_credentials_including_scalar_values(secret):
    import json

    from api.domains.custom_api.request import redact

    value = json.loads(secret) if secret in {"123456789", "true", "null"} else secret
    assert redact({secret: [value]}, [secret]) == {"[REDACTED]": ["[REDACTED]"]}


def test_scope_matches_configured_effective_port():
    check_scope("https://api.example.com:8443/v1", "https://api.example.com:8443/v1/items")
    check_scope("https://api.example.com:443/v1", "https://api.example.com/v1/items")
    with pytest.raises(RequestRefused):
        check_scope("https://api.example.com:8443/v1", "https://api.example.com/v1/items")


@pytest.mark.parametrize(
    "auth,expected",
    [
        ({"type": "bearer", "token": "fixture-token"}, {"authorization": "Bearer fixture-token"}),
        ({"type": "basic", "username": "user", "password": "pass"}, {"authorization": "Basic dXNlcjpwYXNz"}),
        ({"type": "api_key", "header_name": "X-Api-Key", "token": "key"}, {"x-api-key": "key"}),
    ],
)
def test_authentication_materializes_only_the_selected_scheme(auth, expected):
    from hamcrest import assert_that, equal_to

    headers, _ = credential_headers({"auth": auth})
    assert_that(headers, equal_to(expected))


def test_configured_headers_cannot_be_overridden_and_no_network_is_touched(monkeypatch):
    from api.domains.custom_api.request import execute

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: pytest.fail("DNS must not run for refused headers"))
    for name in ["Authorization", "HOST", "x-api-key", "Transfer-Encoding"]:
        with pytest.raises(RequestRefused):
            execute(
                {
                    "base_url": "https://api.example.com/v1",
                    "auth": {"type": "api_key", "header_name": "X-API-Key", "token": "key"},
                },
                {"url": "https://api.example.com/v1/items", "headers": [{"name": name, "value": "override"}]},
            )


def test_request_uses_pinned_address_and_never_follows_redirect(monkeypatch):
    from hamcrest import assert_that, equal_to, has_length

    from api.domains.custom_api import request as engine

    sent = []

    class Response:
        status = 302

    class Connection:
        def __init__(self, host, address, port):
            assert_that((host, address, port), equal_to(("api.example.com", "8.8.8.8", 8443)))

        def request(self, method, path, body=None, headers=None):
            sent.append({"path": path, "headers": headers})

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(engine, "public_addresses", lambda host, port: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", Connection)
    with pytest.raises(RequestRefused, match="Redirect"):
        engine.execute(
            {"base_url": "https://api.example.com:8443/v1", "auth": {"type": "bearer", "token": "fixture"}},
            {"url": "https://api.example.com:8443/v1/items"},
        )
    assert_that(sent, has_length(1))


def test_json_and_text_response_values_are_bounded_and_known_secrets_redacted(monkeypatch):
    from hamcrest import assert_that, equal_to

    from api.domains.custom_api import request as engine

    class Connection:
        def __init__(self, *args):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self

        status = 200

        def read(self, limit):
            return b'{"echo":"fixture-token","items":[1]}'

        def close(self):
            pass

    monkeypatch.setattr(engine, "public_addresses", lambda *args: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", Connection)
    result = engine.execute(
        {"base_url": "https://api.example.com/v1", "auth": {"type": "bearer", "token": "fixture-token"}},
        {"url": "https://api.example.com/v1/items"},
    )
    assert_that(result, equal_to({"status": 200, "body": {"echo": "[REDACTED]", "items": [1]}}))
