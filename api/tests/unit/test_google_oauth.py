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
    base = {
        "secret_signing_key": "test-signing-key",
        "web_app_url": "http://localhost:3000",
        "google_cloud_client_id": "client-id.apps.googleusercontent.com",
        "google_cloud_client_secret": "client-secret",
    }
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
    assert oauth._redirect_uri(_config()) == "http://localhost:3000/api/v1/integrations/google/callback"


def test_state_round_trip_returns_provider():
    cfg = _config()
    state = oauth._encode_state(cfg, "google_workspace")
    assert oauth._provider_from_state(state, cfg) == "google_workspace"


def test_state_rejects_wrong_signing_key():
    state = oauth._encode_state(_config(), "google_workspace")
    assert oauth._provider_from_state(state, _config(secret_signing_key="other")) is None


def test_state_rejects_wrong_token_type():
    cfg = _config()
    forged = jwt.encode({"typ": "access"}, cfg.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)
    assert oauth._provider_from_state(forged, cfg) is None


def test_state_rejects_garbage():
    assert oauth._provider_from_state("not-a-jwt", _config()) is None


def test_state_rejects_unknown_provider():
    cfg = _config()
    state = oauth._encode_state(cfg, "dropbox")
    assert oauth._provider_from_state(state, cfg) is None


def test_state_naming_a_retired_provider_is_rejected():
    # gmail/google_sheets states may still be in flight from an old popup; they must not
    # resolve now that nothing materializes those providers.
    cfg = _config()
    for retired in ("gmail", "google_sheets", "google_calendar"):
        assert oauth._provider_from_state(oauth._encode_state(cfg, retired), cfg) is None


# --- authorize-url ---


def test_authorize_url_contains_expected_params():
    url = oauth.google_authorize_url(_context=_NO_CONTEXT, services="gmail", config=_config())["authorize_url"]
    assert url.startswith(oauth.GOOGLE_AUTH_ENDPOINT)
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "gmail.modify" in url
    assert "client-id.apps.googleusercontent.com" in url


def test_authorize_url_rejects_retired_provider():
    # The per-service Google providers are gone; a stale caller must fail loudly rather
    # than consent to scopes no integration can use.
    for retired in ("gmail", "google_sheets", "google_calendar"):
        with pytest.raises(HTTPException) as exc:
            oauth.google_authorize_url(_context=_NO_CONTEXT, provider=retired, services="gmail", config=_config())
        assert exc.value.status_code == 400


def test_authorize_url_rejects_unknown_provider():
    with pytest.raises(HTTPException) as exc:
        oauth.google_authorize_url(_context=_NO_CONTEXT, provider="dropbox", config=_config())
    assert exc.value.status_code == 400


def test_authorize_url_requires_configured_client():
    with pytest.raises(HTTPException) as exc:
        oauth.google_authorize_url(_context=_NO_CONTEXT, services="gmail", config=_config(google_cloud_client_id=""))
    assert exc.value.status_code == 503


def test_authorize_url_uses_custom_client_id_without_config():
    # A user-supplied client id works even when the app-owned client is unconfigured;
    # only the id is needed here (the secret is supplied later to /token).
    url = oauth.google_authorize_url(
        _context=_NO_CONTEXT,
        client_id="custom.apps.googleusercontent.com",
        services="gmail",
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
    state = oauth._encode_state(cfg, "google_workspace")
    resp = oauth.google_callback(config=cfg, code="auth-code", state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert msg["type"] == oauth.MESSAGE_TYPE
    assert msg["provider"] == "google_workspace"
    assert msg["code"] == "auth-code"
    assert "error" not in msg


def test_callback_echoes_the_provider_from_state():
    cfg = _config()
    state = oauth._encode_state(cfg, "google_workspace")
    resp = oauth.google_callback(config=cfg, code="auth-code", state=state, error=None)
    assert _extract_message(resp.body.decode())["provider"] == "google_workspace"


def test_callback_rejects_invalid_state():
    resp = oauth.google_callback(config=_config(), code="c", state="bad", error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
    assert "code" not in msg


def test_callback_requires_code():
    cfg = _config()
    state = oauth._encode_state(cfg, "google_workspace")
    resp = oauth.google_callback(config=cfg, code=None, state=state, error=None)
    msg = _extract_message(resp.body.decode())
    assert "error" in msg
    assert "code" not in msg


def test_callback_propagates_google_denial():
    resp = oauth.google_callback(config=_config(), code=None, state=None, error="access_denied")
    msg = _extract_message(resp.body.decode())
    assert "access_denied" in msg["error"]


# --- token exchange ---


def _token_request(**overrides):
    base = {"code": "auth-code"}
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
        return SimpleNamespace(status_code=200, json=lambda: {"refresh_token": "rt-123"})

    monkeypatch.setattr(oauth.httpx, "post", fake_post)
    result = oauth.google_token_exchange(body=_token_request(), _context=_NO_CONTEXT, config=cfg)
    # Providers that don't request the openid scopes get no email, and the legacy
    # refresh_token key stays exactly where callers expect it.
    assert result == {"refresh_token": "rt-123", "granted_scopes": [], "email": None}


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
        _context=_NO_CONTEXT,
        config=cfg,
    )
    assert result["refresh_token"] == "rt-x"


def test_token_exchange_requires_configured_client(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: pytest.fail("exchange attempted without a configured client"),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(
            body=_token_request(),
            _context=_NO_CONTEXT,
            config=_config(google_cloud_client_id="", google_cloud_client_secret=""),
        )
    assert exc.value.status_code == 503


def test_token_exchange_errors_when_no_refresh_token(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"access_token": "at-only"}),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(body=_token_request(), _context=_NO_CONTEXT, config=_config())
    assert exc.value.status_code == 400


def test_token_exchange_errors_on_non_200(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=400, json=dict),
    )
    with pytest.raises(HTTPException) as exc:
        oauth.google_token_exchange(body=_token_request(), _context=_NO_CONTEXT, config=_config())
    assert exc.value.status_code == 400


# --- google_workspace: per-request scope derivation ---

_WORKSPACE = "google_workspace"


def _workspace_url(services: str, read_only: bool = False, **cfg_overrides) -> str:
    return oauth.google_authorize_url(
        _context=_NO_CONTEXT,
        provider=_WORKSPACE,
        services=services,
        read_only=read_only,
        config=_config(**cfg_overrides),
    )["authorize_url"]


def test_workspace_scopes_are_derived_from_selected_services():
    assert oauth.workspace_scopes(["gmail", "calendar"], read_only=False) == (
        "email",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
        "https://www.googleapis.com/auth/gmail.settings.sharing",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    )


def test_workspace_scopes_read_only_uses_readonly_variants():
    scopes = oauth.workspace_scopes(["gmail", "calendar", "drive"], read_only=True)
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert "https://www.googleapis.com/auth/calendar.readonly" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes
    # No write scope may slip through when the user asked for read-only.
    assert not any(s.endswith(("gmail.modify", "auth/calendar", "auth/drive")) for s in scopes)


def test_workspace_scopes_dedupe_overlapping_services():
    # gog's sheets service also needs Drive, so sheets+drive must not repeat it.
    scopes = oauth.workspace_scopes(["sheets", "drive"], read_only=False)
    assert scopes.count("https://www.googleapis.com/auth/drive") == 1
    assert "https://www.googleapis.com/auth/spreadsheets" in scopes


def test_workspace_scopes_always_include_identity_scopes():
    # The account email is read out of the id_token, so these are non-negotiable.
    for service in ("gmail", "calendar", "drive", "sheets"):
        scopes = oauth.workspace_scopes([service], read_only=False)
        assert {"openid", "email", "https://www.googleapis.com/auth/userinfo.email"} <= set(scopes)


def test_workspace_authorize_url_includes_derived_scopes():
    url = _workspace_url("gmail,drive")
    assert "gmail.modify" in url
    assert "auth%2Fdrive" in url
    assert "openid" in url


def test_workspace_authorize_url_rejects_empty_services():
    with pytest.raises(HTTPException) as exc:
        _workspace_url("")
    assert exc.value.status_code == 400


def test_workspace_authorize_url_rejects_unknown_service():
    with pytest.raises(HTTPException) as exc:
        _workspace_url("gmail,youtube")
    assert exc.value.status_code == 400
    assert "youtube" in exc.value.detail


def test_state_round_trips_workspace_provider():
    cfg = _config()
    state = oauth._encode_state(cfg, _WORKSPACE)
    assert oauth._provider_from_state(state, cfg) == _WORKSPACE


def test_callback_echoes_workspace_provider():
    cfg = _config()
    # error=None explicitly: direct-calling the route leaves the Query() sentinel in
    # place otherwise, and it reads as truthy.
    resp = oauth.google_callback(
        config=cfg,
        code="abc",
        state=oauth._encode_state(cfg, _WORKSPACE),
        error=None,
    )
    msg = _extract_message(resp.body.decode())
    assert msg["provider"] == _WORKSPACE
    assert msg["code"] == "abc"


def test_token_exchange_returns_email_and_granted_scopes(monkeypatch):
    # Signed with an unrelated key on purpose: the route decodes without verifying,
    # because the token came straight from Google over TLS in our own request.
    id_token = jwt.encode({"email": "user@example.com"}, "irrelevant", algorithm=JWT_ENCODING_ALGORITHM)
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(
            status_code=200,
            json=lambda: {
                "refresh_token": "rt-ws",
                "scope": "openid https://www.googleapis.com/auth/gmail.readonly",
                "id_token": id_token,
            },
        ),
    )
    result = oauth.google_token_exchange(body=_token_request(), _context=_NO_CONTEXT, config=_config())
    assert result["refresh_token"] == "rt-ws"
    assert result["email"] == "user@example.com"
    assert result["granted_scopes"] == ["openid", "https://www.googleapis.com/auth/gmail.readonly"]


def test_token_exchange_tolerates_unreadable_id_token(monkeypatch):
    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(
            status_code=200,
            json=lambda: {"refresh_token": "rt", "id_token": "not-a-jwt"},
        ),
    )
    result = oauth.google_token_exchange(body=_token_request(), _context=_NO_CONTEXT, config=_config())
    assert result["email"] is None
