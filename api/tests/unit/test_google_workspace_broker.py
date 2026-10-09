"""Google Workspace token brokering and the pod-side gog artifacts."""

from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, is_not

from api.domains.agents.gog_artifacts import (
    build_gog_env,
    build_gog_shim_install_sh,
    build_gog_shim_sh,
)
from api.domains.agents.models import GoogleWorkspaceContent, required_service_scopes
from api.domains.integrations.plugins.base import EgressMode, UpstreamAuthenticationError
from api.domains.integrations.plugins.providers import GoogleWorkspacePlugin

_SERVICES = ["gmail", "sheets"]

REFRESH_TOKEN = "1//09_the_renewable_grant"
CLIENT_SECRET = "GOCSPX-the_client_secret"


def _content(**overrides) -> GoogleWorkspaceContent:
    read_only = overrides.get("read_only", False)
    defaults = {
        "email": "user@example.com",
        "services": _SERVICES,
        "scopes": sorted(required_service_scopes(_SERVICES, read_only)),
        "refresh_token": REFRESH_TOKEN,
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": CLIENT_SECRET,
    }
    defaults.update(overrides)
    return GoogleWorkspaceContent.model_validate(defaults)


def _token_response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    return response


# --- minting ---


def test_google_workspace_brokers_rather_than_proxies():
    # gog exposes no base-URL override but does accept a pre-minted token, so the pod
    # gets an expiring credential rather than the gateway sitting on every request.
    assert_that(GoogleWorkspacePlugin().egress_mode, is_(equal_to(EgressMode.TOKEN_BROKER)))


def test_minting_exchanges_the_refresh_token_and_returns_only_the_access_token():
    response = _token_response({"access_token": "ya29.minted", "expires_in": 3599, "scope": "a b"})
    with patch("api.domains.integrations.plugins.providers.httpx.post", return_value=response) as post:
        minted = GoogleWorkspacePlugin().mint_upstream_token(_content())

    assert_that(minted.value, equal_to("ya29.minted"))
    assert_that(minted.expires_in, equal_to(3599))
    sent = post.call_args.kwargs["data"]
    assert_that(sent["grant_type"], equal_to("refresh_token"))
    assert_that(sent["refresh_token"], equal_to(REFRESH_TOKEN))
    # The renewable half of the grant is what the pod must never receive.
    assert_that(REFRESH_TOKEN in minted.value, is_(False))
    assert_that(CLIENT_SECRET in minted.value, is_(False))


def test_minting_reports_the_scopes_google_actually_granted():
    # A user can trim the grant at myaccount.google.com after consent, so the stored
    # scopes are a request, not a fact.
    response = _token_response({"access_token": "ya29.x", "expires_in": 3599, "scope": "gmail.readonly"})
    with patch("api.domains.integrations.plugins.providers.httpx.post", return_value=response):
        minted = GoogleWorkspacePlugin().mint_upstream_token(_content())
    assert_that(minted.scopes, equal_to(frozenset({"gmail.readonly"})))


def test_minting_falls_back_to_the_stored_scopes_when_google_omits_them():
    response = _token_response({"access_token": "ya29.x", "expires_in": 3599})
    with patch("api.domains.integrations.plugins.providers.httpx.post", return_value=response):
        minted = GoogleWorkspacePlugin().mint_upstream_token(_content())
    assert_that(minted.scopes, equal_to(frozenset(_content().scopes)))


@pytest.mark.parametrize(
    "response",
    [
        _token_response({"error": "invalid_grant"}, status_code=400),
        _token_response({"expires_in": 3599}),
        _token_response({"access_token": ""}),
    ],
    ids=["rejected", "no_access_token", "empty_access_token"],
)
def test_a_bad_token_response_is_an_authentication_failure_not_a_silent_pass(response):
    with patch("api.domains.integrations.plugins.providers.httpx.post", return_value=response):
        with pytest.raises(UpstreamAuthenticationError):
            GoogleWorkspacePlugin().mint_upstream_token(_content())


def test_a_credential_without_an_oauth_client_cannot_mint():
    with pytest.raises(UpstreamAuthenticationError):
        GoogleWorkspacePlugin().mint_upstream_token(_content(client_id="", client_secret=""))


# --- pod artifacts ---


def test_pods_receive_no_refresh_token_client_secret_or_keyring():
    env = build_gog_env(_content(), "/home/node", gateway_base_url="https://gw/gateway/v1")
    serialized = repr(sorted(env.items()))
    assert_that(REFRESH_TOKEN in serialized, is_(False))
    assert_that(CLIENT_SECRET in serialized, is_(False))
    assert_that(set(env), equal_to({"GOG_HOME", "GOG_ACCOUNT_EMAIL", "AF_GATEWAY_TOKEN_URL"}))
    assert_that(env["AF_GATEWAY_TOKEN_URL"], equal_to("https://gw/gateway/v1/token"))


def test_the_readonly_guard_survives_brokering():
    env = build_gog_env(_content(read_only=True), "/home/node", gateway_base_url="https://gw/gateway/v1")
    assert_that(env["GOG_READONLY"], equal_to("1"))


def test_the_shim_execs_the_real_binary_by_absolute_path():
    # Resolved from PATH it would find itself; the absolute path is what stops recursion.
    shim = build_gog_shim_sh()
    assert_that(shim, contains_string("exec /usr/local/bin/gog "))


def test_the_shim_fetches_a_token_per_invocation():
    # A Google access token lasts about an hour and agents run for days, so a boot-time
    # fetch would work until it silently stopped.
    shim = build_gog_shim_sh()
    assert_that(shim, contains_string("$AF_GATEWAY_TOKEN_URL"))
    assert_that(shim, contains_string("AF_GATEWAY_TOKEN_GOOGLE_WORKSPACE"))


def test_the_shim_carries_no_credential_material():
    # It ships in a ConfigMap, so anything interpolated into it is world-readable.
    shim = build_gog_shim_sh()
    assert_that(REFRESH_TOKEN in shim, is_(False))
    assert_that(CLIENT_SECRET in shim, is_(False))


def test_the_shim_distinguishes_a_missing_credential_from_a_gateway_failure():
    shim = build_gog_shim_sh()
    assert_that(shim, contains_string("exit 78"))
    assert_that(shim, contains_string("exit 77"))


def test_the_installer_puts_the_shim_ahead_of_the_real_binary():
    install = build_gog_shim_install_sh("/home/hermes")
    assert_that(install, contains_string("/home/hermes/.local/bin/gog"))
    assert_that(install, contains_string("chmod 755"))
    assert_that(install, is_not(contains_string("gog auth")))
