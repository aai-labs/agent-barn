"""Steps for signing in with Google, with Google's token endpoint faked out."""

import urllib.parse
from dataclasses import dataclass, field

from injector import Module, provider, singleton

from api.core.config import Config
from api.infrastructure.google.identity import GoogleIdentity, GoogleIdentityClient

WEB_APP_URL = "https://farm.example.com"
GOOGLE_SUB = "google-sub-1234567890"
GOOGLE_EMAIL = "jane@example.com"


def google_identity(
    *, sub: str = GOOGLE_SUB, email: str = GOOGLE_EMAIL, verified: bool = True, name: str | None = "Jane Doe"
) -> GoogleIdentity:
    return GoogleIdentity(sub=sub, email=email, email_verified=verified, name=name)


@dataclass
class FakeGoogleIdentity(GoogleIdentityClient):
    """Stands in for Google's token endpoint and records the codes it was asked to redeem."""

    exchange_result: GoogleIdentity | Exception = field(default_factory=google_identity)
    exchanges: list[dict] = field(default_factory=list)
    is_configured: bool = True

    @property
    def configured(self) -> bool:
        return self.is_configured

    def exchange_code(self, **kwargs) -> GoogleIdentity:
        self.exchanges.append(kwargs)
        if isinstance(self.exchange_result, Exception):
            raise self.exchange_result
        return self.exchange_result


class FakeGoogleIdentityModule(Module):
    @provider
    @singleton
    def provide_google_identity(self, config: Config) -> GoogleIdentityClient:
        return FakeGoogleIdentity(config)


def fake_google(context) -> FakeGoogleIdentity:
    identity = context.injector.get(GoogleIdentityClient)
    assert isinstance(identity, FakeGoogleIdentity)
    return identity


def google_returns(result: GoogleIdentity | Exception):
    def step(context):
        fake_google(context).exchange_result = result

    return step


def start_google_sign_in(context, origin: str = "signup"):
    return context.client.get("/api/v1/auth/google/start", params={"origin": origin}, follow_redirects=False)


def state_from(start_response) -> str:
    location = start_response.headers["location"]
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))["state"]


def finish_google_sign_in(context, origin: str = "signup", **params):
    """Start sign-in, then come back from Google with a code for its state."""
    state = state_from(start_google_sign_in(context, origin))
    return context.client.get(
        "/api/v1/auth/google/callback",
        params={"code": "the-code", "state": state, **params},
        follow_redirects=False,
    )


def redirect_target(response) -> tuple[str, dict[str, str]]:
    location = urllib.parse.urlparse(response.headers["location"])
    return f"{location.scheme}://{location.netloc}{location.path}", dict(urllib.parse.parse_qsl(location.query))
