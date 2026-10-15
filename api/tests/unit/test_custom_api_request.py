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
