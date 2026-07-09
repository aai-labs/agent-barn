"""Google OAuth 2.0 authorization-code flow for the Gmail skill.

Replaces the old hand-pasted client_id/client_secret/refresh_token fields with a
single "Authenticate with Google" button. The frontend opens a popup, fetches the
authorize URL from ``/authorize-url`` (authenticated), and points the popup at Google.
Google redirects the popup to ``/callback`` (proxied through the UI origin so it is
same-origin with the opener); the callback exchanges the code for a refresh token using
the app-owned client credentials from config, then serves a tiny HTML page that
``postMessage``s the refresh token back to the opener and closes.

Only the refresh token is persisted (as a ``gmail`` AgentSecret via the normal agent
create/update path); the client id/secret stay in config and are injected into the
agent's aai-cli profile at start time.
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

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.auth.utils import get_current_user

integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])

# Read-only Gmail access — the scope the aai-cli gmail-work profile needs to list mail.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Client-side message contract (see use-google-oauth.ts).
MESSAGE_TYPE = "google-oauth"
PROVIDER = "gmail"

_STATE_TTL_SECONDS = 600
_STATE_TYPE = "google_oauth_state"
_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 30


def _redirect_uri(config: Config) -> str:
    # Must be byte-identical between authorize-url and the token exchange, and must be a
    # registered redirect URI on the Google OAuth client (Web application type).
    return f"{config.web_app_url}/api/v1/integrations/google/callback"


def _encode_state(config: Config) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    return jwt.encode(
        payload, config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM
    )


def _state_is_valid(state: str, config: Config) -> bool:
    try:
        payload = jwt.decode(
            state, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM]
        )
    except InvalidTokenError:
        return False
    return payload.get("typ") == _STATE_TYPE


def _post_message_html(
    config: Config,
    *,
    refresh_token: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """HTML that posts the result back to the opener window and closes the popup.

    ``targetOrigin`` is the app's own origin (``web_app_url``) — the popup is served on
    that same origin (Next.js proxies ``/api/*`` to the backend), so the opener's origin
    check matches.
    """
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "provider": PROVIDER, "error": error}
        blurb = "Authentication failed. You can close this window."
    else:
        message = {
            "type": MESSAGE_TYPE,
            "provider": PROVIDER,
            "refreshToken": refresh_token,
        }
        blurb = "Authentication complete. You can close this window."

    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Google authentication</title></head>
<body style="font-family: system-ui, -apple-system, sans-serif; padding: 24px; color: #333;">
<p>{blurb}</p>
<script>
  (function () {{
    var msg = {json.dumps(message)};
    if (window.opener) {{
      window.opener.postMessage(msg, {json.dumps(config.web_app_url)});
    }}
    window.close();
  }})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@integrations_router.get("/google/authorize-url")
def google_authorize_url(
    _context: Annotated[CurrentUserContext, Depends(get_current_user())],
    config: Config = Injected(Config),
):
    """Return the Google OAuth authorize URL for the popup to navigate to."""
    if not config.google_cloud_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )
    params = {
        "client_id": config.google_cloud_client_id,
        "redirect_uri": _redirect_uri(config),
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _encode_state(config),
    }
    return {"authorize_url": f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"}


@integrations_router.get("/google/callback", response_class=HTMLResponse)
def google_callback(
    config: Config = Injected(Config),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Exchange the authorization code for a refresh token and hand it to the opener."""
    if error:
        return _post_message_html(
            config, error=f"Google authorization was denied or failed ({error})."
        )
    if not state or not _state_is_valid(state, config):
        return _post_message_html(
            config, error="Invalid or expired authorization state. Please try again."
        )
    if not code:
        return _post_message_html(
            config, error="Missing authorization code from Google."
        )

    try:
        resp = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": config.google_cloud_client_id,
                "client_secret": config.google_cloud_client_secret,
                "code": code,
                "redirect_uri": _redirect_uri(config),
                "grant_type": "authorization_code",
            },
            timeout=_TOKEN_EXCHANGE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return _post_message_html(config, error=f"Could not reach Google: {exc}")

    if resp.status_code != 200:
        return _post_message_html(
            config, error="Google rejected the token exchange. Please try again."
        )

    refresh_token = resp.json().get("refresh_token")
    if not refresh_token:
        # Google only returns a refresh token on first consent; prompt=consent should force
        # it, but if the app's access was previously granted without offline access the user
        # may need to revoke it first.
        return _post_message_html(
            config,
            error=(
                "Google did not return a refresh token. Remove this app's access at "
                "myaccount.google.com/permissions, then reconnect."
            ),
        )

    return _post_message_html(config, refresh_token=refresh_token)
