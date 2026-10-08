"""The pure parts of the SharePoint sign-in on a Teams app: scopes, PKCE, signed state, the
authorize and admin-approval URLs, the popup callback page, and the Microsoft token client."""

import base64
import hashlib
import urllib.parse
import uuid
from types import SimpleNamespace
from typing import cast

import httpx
import jwt
import pytest
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    has_item,
    is_not,
    none,
    not_,
    starts_with,
)

from api.core.config import Config
from api.domains.agents.microsoft_graph_scopes import (
    granted_permissions,
    missing_sharepoint_permissions,
    sharepoint_permission,
    sharepoint_scopes,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    build_admin_consent_url,
    build_authorize_url,
    claims_from_id_token,
    pkce_pair,
)
from api.domains.agents.sharepoint_service import (
    SignInState,
    callback_html,
    decode_sign_in_state,
    encode_sign_in_state,
    sign_in_redirect_uri,
)
from api.domains.integrations.google_oauth.routes import _encode_state as encode_google_state

_KEY = "unit-test-signing-key-with-enough-length"
_ENCRYPTION_KEY = "wS7t1bG1JvH1l0Yk1QmC4z9oQ0mZ5c3YtqVnGmX7c2E="
_CONFIG = cast(
    Config,
    SimpleNamespace(
        secret_signing_key=_KEY,
        agent_token_encryption_key=_ENCRYPTION_KEY,
        web_app_url="https://farm.example.com",
    ),
)
_TENANT = "22222222-2222-4222-8222-222222222222"
_APP_ID = "11111111-1111-4111-8111-111111111111"


def _state(**overrides) -> SignInState:
    values = {
        "agent_id": uuid.uuid4(),
        "connection_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "read_only": False,
        "code_verifier": "verifier-" + "x" * 50,
    }
    values.update(overrides)
    return SignInState(**values)


def _query(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# --- scopes -------------------------------------------------------------------------


def test_write_access_requests_readwrite_offline_access_and_identity():
    assert_that(
        sharepoint_scopes(read_only=False),
        equal_to(
            (
                "email",
                "https://graph.microsoft.com/Sites.ReadWrite.All",
                "offline_access",
                "openid",
                "profile",
            )
        ),
    )


def test_read_only_requests_the_read_scope():
    assert_that(sharepoint_scopes(read_only=True), has_item("https://graph.microsoft.com/Sites.Read.All"))
    assert_that(sharepoint_permission(read_only=True), equal_to("Sites.Read.All"))


def test_granted_permissions_compare_bare_names_and_write_implies_read():
    granted = granted_permissions(["https://graph.microsoft.com/Sites.ReadWrite.All", "User.Read"])
    assert_that("Sites.Read.All" in granted, equal_to(True))
    assert_that(missing_sharepoint_permissions(["Sites.ReadWrite.All"], read_only=True), equal_to([]))


def test_missing_permission_is_reported():
    assert_that(missing_sharepoint_permissions(["User.Read"], read_only=False), equal_to(["Sites.ReadWrite.All"]))


# --- PKCE ---------------------------------------------------------------------------


def test_pkce_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert_that(challenge, equal_to(expected))
    assert_that(43 <= len(verifier) <= 128, equal_to(True))


def test_pkce_verifiers_are_unique():
    assert_that(pkce_pair()[0], is_not(equal_to(pkce_pair()[0])))


# --- state --------------------------------------------------------------------------


def test_state_round_trips_including_the_verifier():
    state = _state(read_only=True)
    assert_that(decode_sign_in_state(encode_sign_in_state(_CONFIG, state), _CONFIG), equal_to(state))


def test_the_verifier_is_encrypted_inside_the_state():
    # The state travels through Microsoft and the browser; the verifier must not be readable there.
    state = _state()
    token = encode_sign_in_state(_CONFIG, state)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert_that(str(payload), not_(contains_string(state.code_verifier)))


def test_state_signed_with_another_key_is_rejected():
    other = cast(
        Config,
        SimpleNamespace(
            secret_signing_key="another-signing-key-with-enough-length",
            agent_token_encryption_key=_ENCRYPTION_KEY,
            web_app_url="x",
        ),
    )
    assert_that(decode_sign_in_state(encode_sign_in_state(other, _state()), _CONFIG), none())


def test_garbage_state_is_rejected():
    assert_that(decode_sign_in_state("not-a-jwt", _CONFIG), none())


def test_expired_state_is_rejected():
    token = encode_sign_in_state(_CONFIG, _state(), ttl_seconds=-1)
    assert_that(decode_sign_in_state(token, _CONFIG), none())


def test_a_google_state_cannot_be_replayed_as_a_sharepoint_sign_in():
    google = encode_google_state(_CONFIG, "google_workspace")
    assert_that(decode_sign_in_state(google, _CONFIG), none())


# --- URLs ---------------------------------------------------------------------------


def test_authorize_url_uses_the_teams_app_its_tenant_and_pkce():
    url = build_authorize_url(
        tenant_id=_TENANT,
        client_id=_APP_ID,
        redirect_uri=sign_in_redirect_uri(_CONFIG),
        scopes=sharepoint_scopes(read_only=False),
        state="signed",
        code_challenge="the-challenge",
    )

    assert_that(url, starts_with(f"https://login.microsoftonline.com/{_TENANT}/oauth2/v2.0/authorize?"))
    assert_that(
        _query(url),
        has_entries(
            client_id=_APP_ID,
            redirect_uri="https://farm.example.com/api/v1/integrations/microsoft/callback",
            response_type="code",
            response_mode="query",
            state="signed",
            scope=" ".join(sharepoint_scopes(read_only=False)),
            code_challenge="the-challenge",
            code_challenge_method="S256",
        ),
    )


def test_authorize_url_does_not_force_the_consent_prompt():
    # prompt=consent would show the consent screen on every reconnect, and where only
    # administrators may consent it would stop non-admins even after approval.
    url = build_authorize_url(
        tenant_id=_TENANT,
        client_id=_APP_ID,
        redirect_uri="https://x/cb",
        scopes=("openid",),
        state="s",
        code_challenge="c",
    )
    assert_that(_query(url).get("prompt"), not_(equal_to("consent")))


def test_admin_consent_url_asks_for_the_sharepoint_permission_on_the_tenant():
    url = build_admin_consent_url(
        tenant_id=_TENANT,
        client_id=_APP_ID,
        redirect_uri="https://farm.example.com/api/v1/integrations/microsoft/callback",
        read_only=False,
    )
    assert_that(url, starts_with(f"https://login.microsoftonline.com/{_TENANT}/v2.0/adminconsent?"))
    assert_that(
        _query(url),
        has_entries(
            client_id=_APP_ID,
            scope="https://graph.microsoft.com/Sites.ReadWrite.All",
            redirect_uri="https://farm.example.com/api/v1/integrations/microsoft/callback",
        ),
    )


# --- callback page ------------------------------------------------------------------


def test_callback_hands_code_and_state_to_the_opener():
    html = bytes(callback_html(_CONFIG, code="the-code", state="the-state").body).decode()
    assert_that(html, contains_string('"code": "the-code"'))
    assert_that(html, contains_string('"state": "the-state"'))
    assert_that(html, contains_string('"https://farm.example.com"'))


def test_callback_confirms_an_administrator_approval():
    html = bytes(callback_html(_CONFIG, admin_consent=True).body).decode()
    assert_that(html, contains_string('"adminConsent": true'))
    assert_that(html, contains_string("approved"))


def test_callback_escapes_script_injection_in_the_error():
    html = bytes(callback_html(_CONFIG, error="</script><script>alert(1)</script>").body).decode()
    assert_that(html, not_(contains_string("</script><script>")))


# --- id token -----------------------------------------------------------------------


def test_claims_are_read_from_the_id_token():
    token = jwt.encode({"tid": _TENANT, "preferred_username": "a@contoso.com"}, "k" * 32, algorithm="HS256")
    assert_that(claims_from_id_token(token), has_entries(tid=_TENANT, preferred_username="a@contoso.com"))


def test_missing_or_malformed_id_token_gives_no_claims():
    assert_that(claims_from_id_token(None), equal_to({}))
    assert_that(claims_from_id_token("garbage"), equal_to({}))


# --- token client -------------------------------------------------------------------


class _Recorder:
    def __init__(self, response: httpx.Response | Exception):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, data, timeout):
        self.calls.append((url, data))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _ok(**payload) -> httpx.Response:
    body = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "Sites.Read.All"}
    body.update(payload)
    return httpx.Response(200, json=body)


def _exchange():
    return MicrosoftIdentityClient().exchange_code(
        tenant_id=_TENANT,
        client_id=_APP_ID,
        code="the-code",
        redirect_uri="https://x/cb",
        code_verifier="the-verifier",
        scopes=("openid", "offline_access"),
    )


def test_exchange_redeems_the_code_with_the_verifier_and_no_secret(monkeypatch):
    recorder = _Recorder(_ok())
    monkeypatch.setattr(httpx, "post", recorder)

    tokens = _exchange()

    url, data = recorder.calls[0]
    assert_that(url, equal_to(f"https://login.microsoftonline.com/{_TENANT}/oauth2/v2.0/token"))
    assert_that(
        data,
        equal_to(
            {
                "grant_type": "authorization_code",
                "client_id": _APP_ID,
                "code": "the-code",
                "redirect_uri": "https://x/cb",
                "code_verifier": "the-verifier",
                "scope": "openid offline_access",
            }
        ),
    )
    assert_that(tokens.refresh_token, equal_to("rt"))


def test_a_rejection_carries_microsofts_error_code_and_description(monkeypatch):
    rejected = httpx.Response(401, json={"error": "invalid_client", "error_description": "AADSTS7000218: needs secret"})
    monkeypatch.setattr(httpx, "post", _Recorder(rejected))

    with pytest.raises(MicrosoftIdentityError) as exc:
        _exchange()

    assert_that(exc.value.error, equal_to("invalid_client"))
    assert_that(exc.value.description, contains_string("AADSTS7000218"))


def test_a_network_failure_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", _Recorder(httpx.ConnectError("boom")))

    with pytest.raises(MicrosoftIdentityUnavailable):
        _exchange()
