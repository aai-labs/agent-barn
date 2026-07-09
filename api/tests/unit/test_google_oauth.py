import json
from types import SimpleNamespace
from typing import cast

import jwt
import pytest
from fastapi import HTTPException

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.integrations.google_oauth import routes as oauth

_NO_CONTEXT = cast(CurrentUserContext, None)


def _config(**overrides):
    base = dict(
        secret_signing_key="test-signing-key",
        web_app_url="http://localhost:3000",
        google_cloud_client_id="client-id.apps.googleusercontent.com",
        google_cloud_client_secret="client-secret",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _extract_message(html: str) -> dict:
    """Pull the JSON payload out of the `var msg = {...};` line in the callback HTML."""
    marker = "var msg = "
    start = html.index(marker) + len(marker)
    end = html.index(";", start)
    return json.loads(html[start:end])


# --- redirect uri / state signing ---


def test_redirect_uri_uses_web_app_url():
    assert (
        oauth._redirect_uri(_config())
        == "http://localhost:3000/api/v1/integrations/google/callback"
    )


def test_state_round_trip_valid():
    cfg = _config()
    assert oauth._state_is_valid(oauth._encode_state(cfg), cfg) is True


def test_state_rejects_wrong_signing_key():
    state = oauth._encode_state(_config())
    assert oauth._state_is_valid(state, _config(secret_signing_key="other")) is False


def test_state_rejects_wrong_token_type():
    cfg = _config()
    forged = jwt.encode(
        {"typ": "access"}, cfg.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM
    )
    assert oauth._state_is_valid(forged, cfg) is False


def test_state_rejects_garbage():
    assert oauth._state_is_valid("not-a-jwt", _config()) is False


# --- authorize-url ---


def test_authorize_url_contains_expected_params():
    url = oauth.google_authorize_url(_context=_NO_CONTEXT, config=_config())[
        "authorize_url"
    ]
    assert url.startswith(oauth.GOOGLE_AUTH_ENDPOINT)
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "gmail.readonly" in url
    assert "client-id.apps.googleusercontent.com" in url


def test_authorize_url_requires_configured_client():
    with pytest.raises(HTTPException) as exc:
        oauth.google_authorize_url(
            _context=_NO_CONTEXT, config=_config(google_cloud_client_id="")
        )
    assert exc.value.status_code == 503


# --- callback ---


def test_callback_success_posts_refresh_token(monkeypatch):
    cfg = _config()
    state = oauth._encode_state(cfg)

    def fake_post(url, data: dict[str, str], timeout=None):
        assert url == oauth.GOOGLE_TOKEN_ENDPOINT
        assert data["code"] == "auth-code"
        assert data["client_id"] == cfg.google_cloud_client_id
        assert data["client_secret"] == cfg.google_cloud_client_secret
        assert data["grant_type"] == "authorization_code"
        return SimpleNamespace(
            status_code=200, json=lambda: {"refresh_token": "rt-123"}
        )

    monkeypatch.setattr(oauth.httpx, "post", fake_post)
    resp = oauth.google_callback(config=cfg, code="auth-code", state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert msg["type"] == oauth.MESSAGE_TYPE
    assert msg["provider"] == oauth.PROVIDER
    assert msg["refreshToken"] == "rt-123"
    assert "error" not in msg


def test_callback_rejects_invalid_state(monkeypatch):
    # httpx.post must never be called when state is invalid.
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: pytest.fail("token exchange attempted with invalid state"),
    )
    resp = oauth.google_callback(config=_config(), code="c", state="bad", error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
    assert "refreshToken" not in msg


def test_callback_propagates_google_denial():
    resp = oauth.google_callback(
        config=_config(), code=None, state=None, error="access_denied"
    )
    msg = _extract_message(resp.body.decode())
    assert "access_denied" in msg["error"]


def test_callback_errors_when_no_refresh_token(monkeypatch):
    cfg = _config()
    state = oauth._encode_state(cfg)
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(
            status_code=200, json=lambda: {"access_token": "at-only"}
        ),
    )
    resp = oauth.google_callback(config=cfg, code="c", state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg


def test_callback_errors_on_non_200(monkeypatch):
    cfg = _config()
    state = oauth._encode_state(cfg)
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=400, json=lambda: {}),
    )
    resp = oauth.google_callback(config=cfg, code="c", state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
