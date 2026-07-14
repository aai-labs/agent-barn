import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException

from api.domains.audit_logs.service import AuditLogService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.integrations.google_oauth import routes as oauth

_NO_CONTEXT = cast(CurrentUserContext, None)
_NOOP_AUDIT = cast(AuditLogService, MagicMock())


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


def test_authorize_url_uses_custom_client_id_without_config():
    # A user-supplied client id works even when the app-owned client is unconfigured;
    # only the id is needed here (the secret is supplied later to /token).
    url = oauth.google_authorize_url(
        _context=_NO_CONTEXT,
        client_id="custom.apps.googleusercontent.com",
        config=_config(google_cloud_client_id="", google_cloud_client_secret=""),
    )["authorize_url"]
    assert "custom.apps.googleusercontent.com" in url


# --- callback (relays the raw code; no token exchange here) ---


def test_callback_success_posts_code(monkeypatch):
    # The callback must not perform a token exchange — it only relays the code.
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: pytest.fail("callback must not exchange the code"),
    )
    cfg = _config()
    state = oauth._encode_state(cfg)
    resp = oauth.google_callback(config=cfg, code="auth-code", state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert msg["type"] == oauth.MESSAGE_TYPE
    assert msg["provider"] == oauth.PROVIDER
    assert msg["code"] == "auth-code"
    assert "error" not in msg


def test_callback_rejects_invalid_state():
    resp = oauth.google_callback(config=_config(), code="c", state="bad", error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
    assert "code" not in msg


def test_callback_requires_code():
    cfg = _config()
    state = oauth._encode_state(cfg)
    resp = oauth.google_callback(config=cfg, code=None, state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
    assert "code" not in msg


def test_callback_propagates_google_denial():
    resp = oauth.google_callback(
        config=_config(), code=None, state=None, error="access_denied"
    )
    msg = _extract_message(resp.body.decode())
    assert "access_denied" in msg["error"]


# --- token exchange ---


def _token_request(**overrides):
    base = dict(code="auth-code")
    base.update(overrides)
    return oauth.GoogleTokenExchangeRequest(**base)


def test_token_exchange_success_uses_config_client(monkeypatch):
    cfg = _config()

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
    result = oauth.google_token_exchange(
        body=_token_request(),
        context=_NO_CONTEXT,
        config=cfg,
        audit_log_service=_NOOP_AUDIT,
    )
    assert result == {"refresh_token": "rt-123"}


def test_token_exchange_prefers_custom_client(monkeypatch):
    # A user-supplied client id/secret takes priority over the config values, and works
    # even when the app-owned client is unconfigured.
    cfg = _config(google_cloud_client_id="", google_cloud_client_secret="")

    def fake_post(url, data: dict[str, str], timeout=None):
        assert data["client_id"] == "custom-id"
        assert data["client_secret"] == "custom-secret"
        return SimpleNamespace(status_code=200, json=lambda: {"refresh_token": "rt-x"})

    monkeypatch.setattr(oauth.httpx, "post", fake_post)
    result = oauth.google_token_exchange(
        body=_token_request(client_id="custom-id", client_secret="custom-secret"),
        context=_NO_CONTEXT,
        config=cfg,
        audit_log_service=_NOOP_AUDIT,
    )
    assert result == {"refresh_token": "rt-x"}


def test_token_exchange_requires_configured_client(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: pytest.fail("exchange attempted without a configured client"),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(
            body=_token_request(),
            context=_NO_CONTEXT,
            config=_config(google_cloud_client_id="", google_cloud_client_secret=""),
            audit_log_service=_NOOP_AUDIT,
        )
    assert exc.value.status_code == 503


def test_token_exchange_errors_when_no_refresh_token(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(
            status_code=200, json=lambda: {"access_token": "at-only"}
        ),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(
            body=_token_request(),
            context=_NO_CONTEXT,
            config=_config(),
            audit_log_service=_NOOP_AUDIT,
        )
    assert exc.value.status_code == 400


def test_token_exchange_errors_on_non_200(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=400, json=lambda: {}),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(
            body=_token_request(),
            context=_NO_CONTEXT,
            config=_config(),
            audit_log_service=_NOOP_AUDIT,
        )
    assert exc.value.status_code == 400
