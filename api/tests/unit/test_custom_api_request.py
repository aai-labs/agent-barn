import json
import socket
from typing import ClassVar

import pytest
from hamcrest import assert_that, equal_to

from api.domains.custom_api import request as engine
from api.domains.custom_api.request import RequestRefused, check_scope, credential_headers, public_addresses


class EchoUpstream:
    status = 200

    def __init__(self, *args):
        self.headers = {}

    def request(self, method, path, body=None, headers=None):
        self.headers = headers or {}

    def getresponse(self):
        return self

    def read(self, limit):
        return json.dumps({"user": "alice", "auth": self.headers["authorization"]}).encode()

    def close(self):
        pass


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


def test_basic_auth_username_is_not_redacted_from_responses(monkeypatch):
    monkeypatch.setattr(engine, "public_addresses", lambda *args: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", EchoUpstream)
    result = engine.execute(
        {
            "base_url": "https://api.example.com/v1",
            "auth": {"type": "basic", "username": "alice", "password": "wonderland"},
        },
        {"url": "https://api.example.com/v1/items"},
    )
    assert_that(result, equal_to({"status": 200, "body": {"user": "alice", "auth": "[REDACTED]"}}))


_OAUTH2 = {
    "type": "oauth2_client_credentials",
    "token_url": "https://auth.example.com/oauth/token",
    "client_id": "fixture-client-id",
    "client_secret": "fixture-client-secret",
}


def test_oauth2_configuration_validates_without_producing_a_header():
    headers, sensitive = credential_headers({"auth": _OAUTH2})
    assert_that(headers, equal_to({}))
    assert_that(sensitive, equal_to(["fixture-client-secret"]))


@pytest.mark.parametrize(
    "auth",
    [
        {**_OAUTH2, "token_url": "http://auth.example.com/oauth/token"},
        {**_OAUTH2, "token_url": "https://user:pw@auth.example.com/oauth/token"},
        {**_OAUTH2, "token_url": None},
        {**_OAUTH2, "client_id": ""},
        {**_OAUTH2, "client_secret": "line\nbreak"},
        {**_OAUTH2, "scope": ""},
        {k: v for k, v in _OAUTH2.items() if k != "client_secret"},
    ],
)
def test_oauth2_configuration_refuses_bad_token_urls_and_missing_credentials(auth):
    with pytest.raises(RequestRefused):
        credential_headers({"auth": auth})


def test_oauth2_request_needs_an_access_token_before_any_network_is_touched(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: pytest.fail("DNS must not run without a token"))
    with pytest.raises(RequestRefused, match="credential gateway"):
        engine.execute(
            {"base_url": "https://api.example.com/v1", "auth": _OAUTH2}, {"url": "https://api.example.com/v1/items"}
        )


def test_access_token_applies_only_to_oauth2_connections():
    with pytest.raises(RequestRefused):
        credential_headers({"auth": {"type": "bearer", "token": "fixture"}}, access_token="minted")


def test_oauth2_request_attaches_the_minted_bearer_and_redacts_token_and_secret(monkeypatch):
    class Upstream(EchoUpstream):
        def read(self, limit):
            return json.dumps({"auth": self.headers["authorization"], "leak": "fixture-client-secret"}).encode()

    monkeypatch.setattr(engine, "public_addresses", lambda *args: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", Upstream)
    result = engine.execute(
        {"base_url": "https://api.example.com/v1", "auth": _OAUTH2},
        {"url": "https://api.example.com/v1/items"},
        access_token="minted-token",
    )
    assert_that(result, equal_to({"status": 200, "body": {"auth": "[REDACTED]", "leak": "[REDACTED]"}}))


class TokenEndpoint:
    """A fake pinned connection standing in for an OAuth2 token endpoint."""

    status = 200
    payload: object = {"access_token": "minted-token", "token_type": "Bearer", "expires_in": 7200}
    calls: ClassVar[list[dict]] = []

    def __init__(self, host, address, port=443, timeout=30):
        type(self).calls.append({"host": host, "address": address, "port": port, "timeout": timeout})

    def request(self, method, path, body=None, headers=None):
        type(self).calls[-1].update({"method": method, "path": path, "body": body, "headers": headers})

    def getresponse(self):
        return self

    def read(self, limit):
        payload = self.payload
        return (payload if isinstance(payload, bytes) else json.dumps(payload).encode())[:limit]

    def close(self):
        pass


def _token_endpoint(monkeypatch, status=200, payload=None):
    endpoint = type("Endpoint", (TokenEndpoint,), {"status": status, "calls": []})
    if payload is not None:
        endpoint.payload = payload
    monkeypatch.setattr(engine, "public_addresses", lambda host, port: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", endpoint)
    return endpoint


def test_token_exchange_posts_the_credentials_as_a_form_to_the_pinned_endpoint(monkeypatch):
    endpoint = _token_endpoint(monkeypatch)
    token, lifetime = engine.fetch_access_token({**_OAUTH2, "scope": "read write"})
    assert_that((token, lifetime), equal_to(("minted-token", 7200)))
    call = endpoint.calls[0]
    assert_that(
        (call["host"], call["address"], call["port"], call["timeout"]),
        equal_to(("auth.example.com", "8.8.8.8", 443, 10)),
    )
    assert_that((call["method"], call["path"]), equal_to(("POST", "/oauth/token")))
    assert_that(call["headers"]["content-type"], equal_to("application/x-www-form-urlencoded"))
    assert_that(
        call["body"].decode(),
        equal_to(
            "grant_type=client_credentials&client_id=fixture-client-id&client_secret=fixture-client-secret&scope=read+write"
        ),
    )


@pytest.mark.parametrize(
    "status,payload,refused",
    [
        (401, {"error": "invalid_client"}, True),
        (400, {"error": "invalid_request"}, True),
        (503, "down", False),
        (302, "", False),
        (200, b"<html>not json</html>", False),
        (200, {"token_type": "Bearer"}, False),
        (200, {"access_token": "", "token_type": "Bearer"}, False),
        (200, {"access_token": "minted", "token_type": "MAC"}, False),
        (200, {"access_token": "bad\ttoken"}, False),
        (200, ["minted"], False),
    ],
)
def test_token_exchange_reports_refusals_separately_from_unusable_answers(monkeypatch, status, payload, refused):
    _token_endpoint(monkeypatch, status=status, payload=payload)
    with pytest.raises(engine.TokenExchangeFailed) as failure:
        engine.fetch_access_token(_OAUTH2)
    assert_that(failure.value.refused, equal_to(refused))


def test_token_exchange_treats_an_unreachable_endpoint_as_unavailable(monkeypatch):
    endpoint = _token_endpoint(monkeypatch)

    def request(self, *args, **kwargs):
        raise OSError("connection reset")

    endpoint.request = request
    with pytest.raises(engine.TokenExchangeFailed) as failure:
        engine.fetch_access_token(_OAUTH2)
    assert_that(failure.value.refused, equal_to(False))


@pytest.mark.parametrize(
    "expires_in,lifetime",
    [(None, 3600), ("soon", 3600), (10**9, 24 * 3600), (-5, 0), ("120", 120)],
)
def test_token_lifetime_is_defaulted_and_bounded(monkeypatch, expires_in, lifetime):
    payload = {"access_token": "minted-token", "token_type": "bearer"}
    if expires_in is not None:
        payload["expires_in"] = expires_in
    _token_endpoint(monkeypatch, payload=payload)
    assert_that(engine.fetch_access_token(_OAUTH2), equal_to(("minted-token", lifetime)))
