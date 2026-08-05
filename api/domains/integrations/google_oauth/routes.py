"""Google OAuth 2.0 authorization-code flow for the Google-backed skills.

Serves every Google provider (see ``PROVIDER_SCOPES``); the caller picks one with the
``provider`` query parameter and the only thing that varies is the requested scope.

Replaces the old hand-pasted client_id/client_secret/refresh_token fields with a
single "Authenticate with Google" button. The frontend opens a popup, fetches the
authorize URL from ``/authorize-url`` (authenticated), and points the popup at Google.
Google redirects the popup to ``/callback`` (proxied through the UI origin so it is
same-origin with the opener); the callback validates the signed ``state`` and
``postMessage``s the raw authorization ``code`` back to the opener. The opener then
calls ``/token`` (authenticated) to exchange the code for a refresh token and closes
the popup.

By default the exchange uses the app-owned client credentials from config. A user may
instead bring their own Google client: the frontend passes ``client_id`` to
``/authorize-url`` (the client id is public and rides in the authorize URL) and both
``client_id``/``client_secret`` to ``/token``. The secret therefore only ever travels
in an authenticated request body — never through Google's authorize endpoint, the
redirect URL, browser history, or our access logs.

The refresh token is persisted as an AgentSecret for the requested provider via the
normal agent create/update path. For the app-owned client, the client id/secret stay in config and
are injected into the agent's aai-cli profile at start time; for a user's own client,
the frontend also persists that client id/secret alongside the refresh token (a refresh
token is bound to the client that issued it).
"""

import json
import time
import urllib.parse
import uuid
from typing import Annotated

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi_injector import Injected
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel

from api.core.config import Config
from api.domains.agents.models import SecretProvider
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.auth.utils import get_current_user

integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])

# Scopes requested per provider — exactly what that provider's aai-cli profile needs.
# Gmail is read-only (listing mail); Sheets is read/write on spreadsheet values, plus
# metadata-only Drive access because `sheets spreadsheets list` discovers spreadsheets
# through drive/v3/files.
PROVIDER_SCOPES: dict[str, tuple[str, ...]] = {
    SecretProvider.GMAIL.value: ("https://www.googleapis.com/auth/gmail.readonly",),
    SecretProvider.GOOGLE_SHEETS.value: (
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ),
}
DEFAULT_PROVIDER = SecretProvider.GMAIL.value

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Client-side message contract (see use-google-oauth.ts).
MESSAGE_TYPE = "google-oauth"

_STATE_TTL_SECONDS = 600
_STATE_TYPE = "google_oauth_state"
_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 30


def _redirect_uri(config: Config) -> str:
    # Must be byte-identical between authorize-url and the token exchange, and must be a
    # registered redirect URI on the Google OAuth client (Web application type).
    return f"{config.web_app_url}/api/v1/integrations/google/callback"


def _encode_state(config: Config, provider: str) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "provider": provider,
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    return jwt.encode(payload, config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)


def _provider_from_state(state: str, config: Config) -> str | None:
    """Return the provider the state was signed for, or None if the state isn't valid.

    Google hands the callback nothing but ``code`` and ``state``, so the provider has to
    ride along inside the signed state to be echoed back to the opener.
    """
    try:
        payload = jwt.decode(state, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
    except InvalidTokenError:
        return None
    if payload.get("typ") != _STATE_TYPE:
        return None
    # States signed before the provider claim existed were all gmail.
    provider = payload.get("provider", DEFAULT_PROVIDER)
    return provider if provider in PROVIDER_SCOPES else None


def _post_message_html(
    config: Config,
    *,
    provider: str,
    code: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """HTML that posts the result back to the opener window and closes the popup.

    Carries the raw authorization ``code`` (not a refresh token) — the opener exchanges
    it via ``/token``. ``targetOrigin`` is the app's own origin (``web_app_url``): the
    popup is served on that same origin (Next.js proxies ``/api/*`` to the backend), so
    the opener's origin check matches.
    """
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "provider": provider, "error": error}
        blurb = "Authentication failed. You can close this window."
    else:
        message = {
            "type": MESSAGE_TYPE,
            "provider": provider,
            "code": code,
        }
        blurb = "Authentication complete. You can close this window."

    # json.dumps does not escape "/", so a payload containing a literal "</script>" (e.g.
    # from the unauthenticated `error` query param) would otherwise close the script block
    # early and inject arbitrary markup/script into the page. Escape "<", ">", "&" as unicode
    # escapes so the JSON stays inert HTML text while still parsing as the same JS value.
    def _script_safe(value: object) -> str:
        return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Google authentication</title></head>
<body style="font-family: system-ui, -apple-system, sans-serif; padding: 24px; color: #333;">
<p>{blurb}</p>
<script>
  (function () {{
    var msg = {_script_safe(message)};
    if (window.opener) {{
      window.opener.postMessage(msg, {_script_safe(config.web_app_url)});
    }}
    window.close();
  }})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@integrations_router.get("/google/authorize-url")
def google_authorize_url(
    _context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    # Plain defaults (not Query(...)) so a direct call resolves to the value rather than
    # the Query sentinel; FastAPI still parses these as optional query parameters.
    client_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    config: Config = Injected(Config),
):
    """Return the Google OAuth authorize URL for the popup to navigate to.

    ``provider`` selects which Google integration is being connected, and so which scopes
    are requested; it defaults to gmail for callers predating the other providers.

    ``client_id`` (optional) selects a user-supplied Google client; when omitted the
    app-owned client from config is used. Only the client id is needed here — it is
    public and travels in the authorize URL — while the matching secret is supplied
    later, to ``/token``.
    """
    scopes = PROVIDER_SCOPES.get(provider)
    if scopes is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported Google provider: {provider}",
        )
    resolved_client_id = client_id or config.google_cloud_client_id
    # For the app-owned client, also require its secret to be configured so we fail
    # before opening consent. A custom client carries its own secret to /token.
    if not resolved_client_id or (not client_id and not config.google_cloud_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )
    params = {
        "client_id": resolved_client_id,
        "redirect_uri": _redirect_uri(config),
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _encode_state(config, provider),
    }
    return {"authorize_url": f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"}


@integrations_router.get("/google/callback", response_class=HTMLResponse)
def google_callback(
    config: Config = Injected(Config),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Validate the signed state and hand the raw authorization code to the opener.

    The code→token exchange happens in ``/token`` (authenticated), so the client secret
    never has to transit this unauthenticated redirect.
    """
    # The provider only exists inside a valid state, so error responses that fire before
    # (or instead of) that validation fall back to the default.
    provider = _provider_from_state(state, config) if state else None
    if error:
        return _post_message_html(
            config,
            provider=provider or DEFAULT_PROVIDER,
            error=f"Google authorization was denied or failed ({error}).",
        )
    if provider is None:
        return _post_message_html(
            config,
            provider=DEFAULT_PROVIDER,
            error="Invalid or expired authorization state. Please try again.",
        )
    if not code:
        return _post_message_html(config, provider=provider, error="Missing authorization code from Google.")
    return _post_message_html(config, provider=provider, code=code)


class GoogleTokenExchangeRequest(BaseModel):
    code: str
    # Optional user-supplied client. When omitted, the app-owned client from config is
    # used. Must be the same client the authorize URL was built with (Google binds the
    # code to its issuing client).
    client_id: str | None = None
    client_secret: str | None = None


@integrations_router.post("/google/token")
def google_token_exchange(
    body: GoogleTokenExchangeRequest,
    _context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    config: Config = Injected(Config),
):
    """Exchange the authorization code for a refresh token.

    Uses the caller-supplied client id/secret when present (a user's own Google client),
    otherwise the app-owned client from config. The secret is read from the request body
    — it never appears in a URL, the authorize request, or our logs.
    """
    client_id = body.client_id or config.google_cloud_client_id
    client_secret = body.client_secret or config.google_cloud_client_secret
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )

    try:
        resp = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": body.code,
                "redirect_uri": _redirect_uri(config),
                "grant_type": "authorization_code",
            },
            timeout=_TOKEN_EXCHANGE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Google: {exc}",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google rejected the token exchange. Please try again.",
        )

    refresh_token = resp.json().get("refresh_token")
    if not refresh_token:
        # Google only returns a refresh token on first consent; prompt=consent should force
        # it, but if the app's access was previously granted without offline access the user
        # may need to revoke it first.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google did not return a refresh token. Remove this app's access at "
                "myaccount.google.com/permissions, then reconnect."
            ),
        )

    return {"refresh_token": refresh_token}
