"""OAuth for MCP servers: discovery, registration, sign-in URLs, and token requests, against a
fake HTTP layer that answers the way MCP servers and authorization servers do."""

import base64
import json
import urllib.parse
from collections.abc import Callable

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_, none

from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.oauth import OAuthError, OAuthRefused, _Response

SERVER = "https://mcp.example.com/mcp"
RESOURCE_METADATA = "https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
ISSUER = "https://auth.example.com"
AS_METADATA = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "registration_endpoint": f"{ISSUER}/register",
    "code_challenge_methods_supported": ["S256"],
    "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
}


def _json(status: int, body: dict, **headers: str) -> _Response:
    return _Response(status, {k.lower(): v for k, v in headers.items()}, json.dumps(body).encode())


Router = Callable[[str, str, bytes | None, dict], _Response]


class FakeWeb:
    """Answers by method and URL, and records every request."""

    def __init__(self, routes: dict[tuple[str, str], _Response]) -> None:
        self.routes = routes
        self.requests: list[dict] = []

    def __call__(self, method: str, url: str, *, body: bytes | None = None, headers: dict | None = None) -> _Response:
        self.requests.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        return self.routes.get((method, url), _Response(404, {}, b""))


def _standard_web(**overrides: _Response) -> FakeWeb:
    routes = {
        ("POST", SERVER): _json(
            401,
            {"error": "unauthorized"},
            **{"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA}", scope="read write"'},
        ),
        ("GET", RESOURCE_METADATA): _json(
            200, {"resource": SERVER, "authorization_servers": [ISSUER], "scopes_supported": ["read"]}
        ),
        ("GET", f"{ISSUER}/.well-known/oauth-authorization-server"): _json(200, AS_METADATA),
    }
    for key, response in overrides.items():
        method, _, url = key.partition(" ")
        routes[(method, url)] = response
    return FakeWeb(routes)


@pytest.fixture
def web(monkeypatch) -> Callable[[FakeWeb], FakeWeb]:
    def install(fake: FakeWeb) -> FakeWeb:
        monkeypatch.setattr(oauth, "_request", fake)
        return fake

    return install


# --- discovery ----------------------------------------------------------------------


def test_discovery_follows_the_challenge_to_the_authorization_server(web):
    web(_standard_web())

    metadata = oauth.discover(SERVER)

    assert_that(metadata.resource, equal_to(SERVER))
    assert_that(metadata.issuer, equal_to(ISSUER))
    assert_that(metadata.token_endpoint, equal_to(f"{ISSUER}/token"))
    assert_that(metadata.registration_endpoint, equal_to(f"{ISSUER}/register"))
    # The challenge's scope wins over the resource's advertised scopes.
    assert_that(metadata.scope, equal_to("read write"))


def test_without_a_metadata_pointer_the_well_known_location_is_tried(web):
    fake = _standard_web(**{f"POST {SERVER}": _json(401, {}, **{"WWW-Authenticate": "Bearer"})})
    web(fake)

    metadata = oauth.discover(SERVER)

    assert_that(metadata.issuer, equal_to(ISSUER))
    assert_that(metadata.scope, equal_to("read"))


def test_a_server_that_needs_no_sign_in_is_refused(web):
    web(_standard_web(**{f"POST {SERVER}": _json(200, {"jsonrpc": "2.0", "id": 1, "result": {}})}))

    with pytest.raises(OAuthError, match="does not ask for a sign-in"):
        oauth.discover(SERVER)


def test_metadata_naming_another_issuer_is_refused(web):
    web(
        _standard_web(
            **{
                f"GET {ISSUER}/.well-known/oauth-authorization-server": _json(
                    200, {**AS_METADATA, "issuer": "https://evil.example.com"}
                )
            }
        )
    )

    with pytest.raises(OAuthError, match="different issuer"):
        oauth.discover(SERVER)


def test_an_authorization_server_without_s256_is_refused(web):
    web(
        _standard_web(
            **{
                f"GET {ISSUER}/.well-known/oauth-authorization-server": _json(
                    200, {**AS_METADATA, "code_challenge_methods_supported": ["plain"]}
                )
            }
        )
    )

    with pytest.raises(OAuthError, match="PKCE"):
        oauth.discover(SERVER)


# --- registration --------------------------------------------------------------------


def _metadata(**changes) -> oauth.OAuthMetadata:
    values = {
        "resource": SERVER,
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register",
        "scope": "read",
        "token_endpoint_auth_methods": ["none", "client_secret_basic"],
    }
    values.update(changes)
    return oauth.OAuthMetadata(**values)


def test_registration_asks_for_a_public_client_where_allowed(web):
    fake = web(FakeWeb({("POST", f"{ISSUER}/register"): _json(201, {"client_id": "abc"})}))

    client = oauth.register(_metadata(), "https://app.example.com/callback")

    sent = json.loads(fake.requests[0]["body"])
    assert_that(
        sent, has_entries(token_endpoint_auth_method="none", redirect_uris=["https://app.example.com/callback"])
    )
    assert_that(
        (client.client_id, client.client_secret, client.token_endpoint_auth_method), equal_to(("abc", None, "none"))
    )


def test_registration_uses_a_secret_when_the_server_requires_one(web):
    fake = web(FakeWeb({("POST", f"{ISSUER}/register"): _json(201, {"client_id": "abc", "client_secret": "s3cret"})}))

    client = oauth.register(_metadata(token_endpoint_auth_methods=["client_secret_post"]), "https://app/cb")

    assert_that(json.loads(fake.requests[0]["body"])["token_endpoint_auth_method"], equal_to("client_secret_post"))
    assert_that(client.client_secret, equal_to("s3cret"))


def test_a_server_without_registration_asks_for_a_client_id():
    with pytest.raises(OAuthError, match="client ID"):
        oauth.register(_metadata(registration_endpoint=None), "https://app/cb")


def test_a_refused_registration_reports_the_reason(web):
    web(FakeWeb({("POST", f"{ISSUER}/register"): _json(400, {"error": "invalid_redirect_uri"})}))

    with pytest.raises(OAuthError, match="invalid_redirect_uri"):
        oauth.register(_metadata(), "https://app/cb")


# --- sign-in and tokens ----------------------------------------------------------------

_CONFIG = {
    "resource": SERVER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "scope": "read",
    "client_id": "abc",
    "client_secret": None,
    "token_endpoint_auth_method": "none",
}


def test_the_authorize_url_carries_pkce_and_the_resource():
    url = oauth.authorize_url(_CONFIG, state="st", code_challenge="ch", redirect_uri="https://app/cb")

    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert_that(
        query,
        has_entries(
            response_type="code",
            client_id="abc",
            state="st",
            code_challenge="ch",
            code_challenge_method="S256",
            resource=SERVER,
            scope="read",
            redirect_uri="https://app/cb",
        ),
    )


def test_a_public_client_exchanges_its_code_with_the_verifier(web):
    fake = web(
        FakeWeb(
            {("POST", f"{ISSUER}/token"): _json(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 600})}
        )
    )

    tokens = oauth.exchange_code(_CONFIG, code="c", code_verifier="v", redirect_uri="https://app/cb")

    form = dict(urllib.parse.parse_qsl(fake.requests[0]["body"].decode()))
    assert_that(
        form,
        has_entries(grant_type="authorization_code", code="c", code_verifier="v", client_id="abc", resource=SERVER),
    )
    assert_that((tokens.access_token, tokens.refresh_token), equal_to(("at", "rt")))


def test_a_confidential_client_authenticates_with_basic(web):
    fake = web(FakeWeb({("POST", f"{ISSUER}/token"): _json(200, {"access_token": "at"})}))
    config = {**_CONFIG, "client_secret": "s3cret", "token_endpoint_auth_method": "client_secret_basic"}

    oauth.exchange_code(config, code="c", code_verifier="v", redirect_uri="https://app/cb")

    expected = "Basic " + base64.b64encode(b"abc:s3cret").decode()
    assert_that(fake.requests[0]["headers"]["authorization"], equal_to(expected))
    assert_that(fake.requests[0]["body"].decode(), is_(contains_string("grant_type=authorization_code")))


def test_a_refresh_that_does_not_rotate_keeps_the_refresh_token(web):
    web(FakeWeb({("POST", f"{ISSUER}/token"): _json(200, {"access_token": "new"})}))

    tokens = oauth.refresh(_CONFIG, "kept")

    assert_that((tokens.access_token, tokens.refresh_token), equal_to(("new", "kept")))


def test_a_refused_grant_means_signing_in_again(web):
    web(FakeWeb({("POST", f"{ISSUER}/token"): _json(400, {"error": "invalid_grant", "error_description": "expired"})}))

    with pytest.raises(OAuthRefused, match="expired"):
        oauth.refresh(_CONFIG, "old")


def test_an_unusable_token_endpoint_is_not_a_refused_grant(web):
    web(FakeWeb({("POST", f"{ISSUER}/token"): _json(503, {})}))

    with pytest.raises(OAuthError) as raised:
        oauth.refresh(_CONFIG, "old")

    assert_that(isinstance(raised.value, OAuthRefused), is_(False))


def test_an_access_token_without_a_lifetime_lasts_an_hour(web):
    web(FakeWeb({("POST", f"{ISSUER}/token"): _json(200, {"access_token": "at"})}))

    tokens = oauth.exchange_code(_CONFIG, code="c", code_verifier="v", redirect_uri="https://app/cb")

    assert_that(tokens.refresh_token, none())
    assert_that(3500 < tokens.expires_at - __import__("time").time() <= 3600, is_(True))
