"""Sign in with Google: OpenID Connect authorization-code flow for Agent Barn accounts.

Only identity is asked for (``openid email profile``), so the consent screen is the
plain "Sign in with Google" one, and no Google API token is kept. The code is redeemed
server-side with the app's client secret, and the id_token in that response names the
account. That token comes straight from Google's token endpoint over TLS, so its claims
are checked rather than its signature (OpenID Connect Core 3.1.3.7, item 6).

This is a different flow from the Gmail and Workspace integration in
``api/domains/integrations/google_oauth``, though both use the same Google client.
"""

import time
import urllib.parse
from dataclasses import dataclass

import httpx
import jwt
from injector import inject, singleton
from jwt.exceptions import InvalidTokenError

from api.core.config import Config

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None


class GoogleIdentityError(Exception):
    """Google refused the code, or answered with a token that isn't for us."""


class GoogleIdentityUnavailable(Exception):
    """Google could not be reached, or answered with something that isn't a token response."""


@inject
@singleton
@dataclass
class GoogleIdentityClient:
    config: Config

    @property
    def configured(self) -> bool:
        return bool(self.config.google_cloud_client_id and self.config.google_cloud_client_secret)

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.config.google_cloud_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            # Someone signed in to several Google accounts picks which one to use.
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> GoogleIdentity:
        try:
            response = httpx.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": self.config.google_cloud_client_id,
                    "client_secret": self.config.google_cloud_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GoogleIdentityUnavailable("Google could not be reached") from exc
        if response.status_code != 200:
            raise GoogleIdentityError(f"Google refused the authorization code ({response.status_code})")
        try:
            id_token = response.json()["id_token"]
            claims = jwt.decode(id_token, options={"verify_signature": False})
        except (KeyError, TypeError, ValueError, InvalidTokenError) as exc:
            raise GoogleIdentityUnavailable("Google answered without a readable id_token") from exc
        return self._identity(claims)

    def _identity(self, claims: dict) -> GoogleIdentity:
        if claims.get("iss") not in _ISSUERS:
            raise GoogleIdentityError("The id_token was not issued by Google")
        if claims.get("aud") != self.config.google_cloud_client_id:
            raise GoogleIdentityError("The id_token was issued to another client")
        expires = claims.get("exp")
        if not isinstance(expires, int | float) or expires <= time.time():
            raise GoogleIdentityError("The id_token has expired")
        sub, email = claims.get("sub"), claims.get("email")
        if not isinstance(sub, str) or not sub or not isinstance(email, str) or not email:
            raise GoogleIdentityError("The id_token names no account")
        name = claims.get("name")
        return GoogleIdentity(
            sub=sub,
            email=email,
            email_verified=claims.get("email_verified") is True,
            name=name if isinstance(name, str) and name.strip() else None,
        )
