import json
import logging
import threading
import time
from urllib.parse import quote

import jwt
from jwt import PyJWKClient

from api.infrastructure.http import resilient_request

logger = logging.getLogger(__name__)

_LOGIN_BASE = "https://login.microsoftonline.com"
_BOT_SCOPE = "https://api.botframework.com/.default"
_JWKS_URL = "https://login.botframework.com/v1/.well-known/keys"
_EXPECTED_ISSUER = "https://api.botframework.com"
_TIMEOUT_SECONDS = 15
_TOKEN_EXPIRY_MARGIN_SECONDS = 60
_JWT_LEEWAY_SECONDS = 300

_token_cache: dict[tuple[str, str], tuple[str, float]] = {}
_token_lock = threading.Lock()
_jwk_client: PyJWKClient | None = None
_jwk_lock = threading.Lock()


class TeamsAuthError(Exception):
    """Raised when Teams credentials or an inbound webhook token are rejected."""


def acquire_token(tenant_id: str, app_id: str, app_password: str) -> str:
    key = (tenant_id, app_id)
    now = time.monotonic()
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

    response = resilient_request(
        "POST",
        f"{_LOGIN_BASE}/{quote(tenant_id, safe='')}/oauth2/v2.0/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        content=(
            f"grant_type=client_credentials&client_id={quote(app_id, safe='')}"
            f"&client_secret={quote(app_password, safe='')}&scope={quote(_BOT_SCOPE, safe='')}"
        ).encode(),
        timeout=_TIMEOUT_SECONDS,
        label="Teams token",
        retry_server_errors=True,
    )
    if response.status_code != 200:
        raise TeamsAuthError(
            "Microsoft rejected the Teams credentials. Check the App ID, client secret value, and Tenant ID."
        )

    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise TeamsAuthError("Microsoft returned no access token for these Teams credentials.")

    expires_in = int(payload.get("expires_in", 0))
    with _token_lock:
        _token_cache[key] = (token, now + max(expires_in - _TOKEN_EXPIRY_MARGIN_SECONDS, 0))
    return token


def send_activity(
    service_url: str,
    conversation_id: str,
    text: str,
    token: str,
    reply_to_activity_id: str | None = None,
) -> str:
    base = f"{service_url.rstrip('/')}/v3/conversations/{quote(conversation_id, safe='')}/activities"
    url = f"{base}/{quote(reply_to_activity_id, safe='')}" if reply_to_activity_id else base
    response = resilient_request(
        "POST",
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        content=json.dumps({"type": "message", "text": text}).encode(),
        timeout=_TIMEOUT_SECONDS,
        label="Teams send",
        retry_server_errors=True,
    )
    response.raise_for_status()
    return str(response.json().get("id") or "")


def verify_inbound_jwt(authorization: str, app_id: str) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise TeamsAuthError("Missing Bot Framework bearer token")

    try:
        signing_key = _signing_key(token)
        jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=app_id,
            issuer=_EXPECTED_ISSUER,
            leeway=_JWT_LEEWAY_SECONDS,
        )
    except TeamsAuthError:
        raise
    except Exception as exc:
        raise TeamsAuthError("Bot Framework token verification failed") from exc


def _signing_key(token: str):
    global _jwk_client
    with _jwk_lock:
        if _jwk_client is None:
            _jwk_client = PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=86_400)
        client = _jwk_client
    return client.get_signing_key_from_jwt(token).key
