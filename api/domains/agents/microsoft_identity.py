"""Microsoft identity platform v2.0: authorize, admin-approval and token requests.

Used for SharePoint, signed in on the agent's Teams app. That app is registered in the
customer's tenant, so every request uses that tenant's authority rather than ``/common``.

The sign-in is a *public client*: the authorization code is redeemed with a PKCE verifier,
never the app's secret. That is what lets aai-cli's ``microsoft_delegated`` profile refresh
the resulting token without a secret too. It requires the redirect URI to be registered under
"Mobile and desktop applications" and "Allow public client flows" to be on; otherwise
Microsoft refuses the redemption with AADSTS7000218.
"""

import base64
import hashlib
import secrets
import urllib.parse
from dataclasses import dataclass

import httpx
import jwt
from injector import singleton
from jwt.exceptions import InvalidTokenError

from api.domains.agents.microsoft_graph_scopes import GRAPH_SCOPE_PREFIX, sharepoint_permission

_LOGIN_HOST = "https://login.microsoftonline.com"
_TIMEOUT_SECONDS = 30


def _tenant(tenant_id: str) -> str:
    return f"{_LOGIN_HOST}/{urllib.parse.quote(tenant_id, safe='')}"


@dataclass(frozen=True)
class MicrosoftTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str
    id_token: str | None


class MicrosoftIdentityError(Exception):
    """Microsoft answered, and refused. ``error`` is its OAuth error code, e.g. ``invalid_client``."""

    def __init__(self, error: str, description: str = ""):
        super().__init__(f"{error}: {description}" if description else error)
        self.error = error
        self.description = description


class MicrosoftIdentityUnavailable(Exception):
    """Microsoft could not be reached, or answered with something that isn't a token response."""


def pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge (RFC 7636)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(
    *,
    tenant_id: str,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": " ".join(scopes),
        # Not prompt=consent: that would show the consent screen again on every reconnect, and
        # in organizations where only administrators may consent it would stop non-admins even
        # after an administrator approved. Microsoft issues a refresh token whenever
        # offline_access is granted, so there is nothing to force.
        "prompt": "select_account",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{_tenant(tenant_id)}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"


def build_admin_consent_url(*, tenant_id: str, client_id: str, redirect_uri: str, read_only: bool) -> str:
    """A link an administrator opens to approve SharePoint access for the whole organization."""
    params = {
        "client_id": client_id,
        "scope": f"{GRAPH_SCOPE_PREFIX}{sharepoint_permission(read_only)}",
        "redirect_uri": redirect_uri,
    }
    return f"{_tenant(tenant_id)}/v2.0/adminconsent?{urllib.parse.urlencode(params)}"


def claims_from_id_token(id_token: str | None) -> dict:
    """Read the claims out of Microsoft's id_token, or {} if unavailable.

    The signature is intentionally not verified: the token was just received in our own
    server-to-server, TLS-protected exchange with Microsoft's token endpoint, not presented
    by a client, so there is no untrusted party between issuance and this line.
    """
    if not id_token:
        return {}
    try:
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except InvalidTokenError:
        return {}
    return claims if isinstance(claims, dict) else {}


@singleton
class MicrosoftIdentityClient:
    def exchange_code(
        self,
        *,
        tenant_id: str,
        client_id: str,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        scopes: tuple[str, ...],
    ) -> MicrosoftTokens:
        """Redeem an authorization code as a public client: the PKCE verifier, no secret."""
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "scope": " ".join(scopes),
        }
        try:
            response = httpx.post(f"{_tenant(tenant_id)}/oauth2/v2.0/token", data=data, timeout=_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise MicrosoftIdentityUnavailable(type(exc).__name__) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise MicrosoftIdentityUnavailable(f"HTTP {response.status_code} without a JSON body") from exc
        if response.status_code != 200:
            if isinstance(payload, dict) and payload.get("error"):
                raise MicrosoftIdentityError(str(payload["error"]), str(payload.get("error_description", "")))
            raise MicrosoftIdentityUnavailable(f"HTTP {response.status_code}")
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise MicrosoftIdentityUnavailable("token response without an access token")
        return MicrosoftTokens(
            access_token=str(payload["access_token"]),
            refresh_token=payload.get("refresh_token"),
            expires_in=int(payload.get("expires_in", 3600)),
            scope=str(payload.get("scope", "")),
            id_token=payload.get("id_token"),
        )
