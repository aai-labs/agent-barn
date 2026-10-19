"""Sign in with Google (AF-368): the authorization code is redeemed for an id_token, whose
claims identify the account. The token comes straight from Google's token endpoint over
TLS, so its claims are checked rather than its signature (OpenID Connect Core 3.1.3.7)."""

import time
import urllib.parse
from types import SimpleNamespace

import httpx
import jwt
import pytest
from hamcrest import assert_that, equal_to, has_entries

from api.infrastructure.google import identity as google
from api.infrastructure.google.identity import (
    GoogleIdentity,
    GoogleIdentityClient,
    GoogleIdentityError,
    GoogleIdentityUnavailable,
)
from api.tests.unit.test_organization_llm import config

CLIENT_ID = "client-id.apps.googleusercontent.com"
REDIRECT = "https://farm.example.com/api/v1/auth/google/callback"


def _client() -> GoogleIdentityClient:
    return GoogleIdentityClient(config(google_cloud_client_id=CLIENT_ID, google_cloud_client_secret="secret"))


def _id_token(**overrides) -> str:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "jane@example.com",
        "email_verified": True,
        "name": "Jane Doe",
        "exp": int(time.time()) + 600,
        **overrides,
    }
    return jwt.encode(claims, "unrelated-key", algorithm="HS256")


def _token_endpoint(monkeypatch, *, status=200, body=None, error=None):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if error is not None:
            raise error
        return SimpleNamespace(status_code=status, json=lambda: body if body is not None else {})

    monkeypatch.setattr(google.httpx, "post", post)
    return calls


def test_the_authorize_url_asks_only_for_identity_and_lets_the_user_pick_an_account():
    url = _client().authorize_url(redirect_uri=REDIRECT, state="signed-state")
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert_that(
        query,
        has_entries(
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT,
            response_type="code",
            scope="openid email profile",
            state="signed-state",
            prompt="select_account",
        ),
    )


def test_a_redeemed_code_yields_the_google_account(monkeypatch):
    calls = _token_endpoint(monkeypatch, body={"id_token": _id_token()})

    identity = _client().exchange_code(code="the-code", redirect_uri=REDIRECT)

    assert_that(
        identity,
        equal_to(GoogleIdentity(sub="1234567890", email="jane@example.com", email_verified=True, name="Jane Doe")),
    )
    assert_that(calls[0][1]["data"], has_entries(code="the-code", redirect_uri=REDIRECT, client_secret="secret"))


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "someone-elses-client"},
        {"iss": "https://evil.example.com"},
        {"exp": int(time.time()) - 1},
        {"sub": ""},
        {"email": None},
    ],
)
def test_an_id_token_not_meant_for_us_is_refused(monkeypatch, claims):
    _token_endpoint(monkeypatch, body={"id_token": _id_token(**claims)})

    with pytest.raises(GoogleIdentityError):
        _client().exchange_code(code="the-code", redirect_uri=REDIRECT)


def test_an_unverified_google_email_is_reported_as_such(monkeypatch):
    _token_endpoint(monkeypatch, body={"id_token": _id_token(email_verified=False)})

    identity = _client().exchange_code(code="the-code", redirect_uri=REDIRECT)

    assert_that(identity.email_verified, equal_to(False))


def test_a_refused_code_is_an_identity_error(monkeypatch):
    _token_endpoint(monkeypatch, status=400, body={"error": "invalid_grant"})

    with pytest.raises(GoogleIdentityError):
        _client().exchange_code(code="reused-code", redirect_uri=REDIRECT)


def test_an_unreachable_google_is_reported_as_unavailable(monkeypatch):
    _token_endpoint(monkeypatch, error=httpx.ConnectError("down"))

    with pytest.raises(GoogleIdentityUnavailable):
        _client().exchange_code(code="the-code", redirect_uri=REDIRECT)


def test_without_a_configured_client_google_sign_in_is_unavailable():
    unconfigured = GoogleIdentityClient(config(google_cloud_client_id="", google_cloud_client_secret=""))

    assert_that(unconfigured.configured, equal_to(False))
