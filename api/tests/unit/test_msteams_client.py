import json
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from hamcrest import assert_that, equal_to, none

from api.infrastructure.msteams import client
from api.infrastructure.msteams.client import (
    TeamsAuthError,
    TeamsDeliveryError,
    acquire_token,
    list_team_channels,
    send_activity,
    verify_inbound_jwt,
)
from api.infrastructure.shared.cache import clear_cache

_APP_ID = "11111111-2222-3333-4444-555555555555"
_ISSUER = "https://api.botframework.com"
_SERVICE_URL = "https://smba.trafficmanager.net/amer/"
_TEAM_ID = "19:0f1e2d3c4b5a6978@thread.tacv2"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


@pytest.fixture(autouse=True)
def _reset_client_state():
    for reset in (lambda: client._token_cache.clear(), clear_cache):
        reset()
    client._jwk_client = None
    yield
    for reset in (lambda: client._token_cache.clear(), clear_cache):
        reset()
    client._jwk_client = None


def _token(**overrides) -> str:
    claims = {
        "iss": _ISSUER,
        "aud": _APP_ID,
        "serviceurl": _SERVICE_URL,
        "exp": int(time.time()) + 600,
        "iat": int(time.time()),
        **overrides,
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


def _verify(token: str, *, service_url: str = _SERVICE_URL) -> None:
    with patch("api.infrastructure.msteams.client._signing_key", return_value=_PUBLIC_KEY):
        verify_inbound_jwt(f"Bearer {token}", _APP_ID, service_url=service_url)


def test_a_well_formed_token_for_this_bot_is_accepted() -> None:
    _verify(_token())


def test_a_token_minted_for_another_bot_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify(_token(aud="99999999-0000-0000-0000-000000000000"))


def test_a_token_from_an_unexpected_issuer_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify(_token(iss="https://evil.example.com"))


def test_a_token_expired_beyond_the_clock_skew_allowance_is_rejected() -> None:
    stale = int(time.time()) - (client._JWT_LEEWAY_SECONDS + 60)

    with pytest.raises(TeamsAuthError):
        _verify(_token(exp=stale))


def test_a_token_expired_within_the_clock_skew_allowance_is_still_accepted() -> None:
    _verify(_token(exp=int(time.time()) - 60))


def test_a_missing_bearer_token_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        verify_inbound_jwt("Bearer   ", _APP_ID, service_url=_SERVICE_URL)


def test_a_malformed_token_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify("not-a-jwt")


def test_a_token_signed_by_an_unknown_key_is_rejected() -> None:
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _APP_ID,
            "serviceurl": _SERVICE_URL,
            "exp": int(time.time()) + 600,
        },
        impostor,
        algorithm="RS256",
    )

    with pytest.raises(TeamsAuthError):
        _verify(forged)


def test_a_token_bound_to_another_service_url_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify(_token(), service_url="https://attacker.example.com/")


def test_a_token_without_a_service_url_claim_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify(_token(serviceurl=None))


def test_an_activity_without_a_service_url_is_rejected() -> None:
    with pytest.raises(TeamsAuthError):
        _verify(_token(), service_url="")


def test_service_url_matching_ignores_trailing_slash_and_case() -> None:
    _verify(_token(serviceurl="https://SMBA.trafficmanager.net/amer"))


@patch("api.infrastructure.msteams.client.resilient_request")
def test_a_token_is_reused_within_its_lifetime(mock_request) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "tok-1", "expires_in": 3600}
    mock_request.return_value = response

    first = acquire_token("tenant-1", _APP_ID, "secret-1")
    second = acquire_token("tenant-1", _APP_ID, "secret-1")

    assert_that(first, equal_to("tok-1"))
    assert_that(second, equal_to("tok-1"))
    assert_that(mock_request.call_count, equal_to(1))


@patch("api.infrastructure.msteams.client.resilient_request")
def test_a_rotated_secret_is_not_served_from_the_previous_secrets_cache_entry(mock_request) -> None:
    old = MagicMock(status_code=200)
    old.json.return_value = {"access_token": "tok-old", "expires_in": 3600}
    new = MagicMock(status_code=200)
    new.json.return_value = {"access_token": "tok-new", "expires_in": 3600}
    mock_request.side_effect = [old, new]

    first = acquire_token("tenant-1", _APP_ID, "secret-old")
    second = acquire_token("tenant-1", _APP_ID, "secret-new")

    assert_that(first, equal_to("tok-old"))
    assert_that(second, equal_to("tok-new"))
    assert_that(mock_request.call_count, equal_to(2))


@patch("api.infrastructure.msteams.client.resilient_request")
def test_rejected_credentials_raise_an_auth_error(mock_request) -> None:
    mock_request.return_value = MagicMock(status_code=401)

    with pytest.raises(TeamsAuthError):
        acquire_token("tenant-1", _APP_ID, "wrong-secret")


@patch("api.infrastructure.msteams.client.resilient_request")
def test_a_token_response_without_an_access_token_raises_an_auth_error(mock_request) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"expires_in": 3600}
    mock_request.return_value = response

    with pytest.raises(TeamsAuthError):
        acquire_token("tenant-1", _APP_ID, "secret-1")


@patch("api.infrastructure.msteams.client.resilient_request")
def test_the_default_general_channel_keeps_its_null_name_for_the_caller_to_localize(mock_request) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"conversations": [{"id": _TEAM_ID}, {"id": "19:abc@thread.tacv2", "name": "ops"}]}
    mock_request.return_value = response

    channels = list_team_channels(_SERVICE_URL, _TEAM_ID, "bot-token")

    assert_that(channels["19:abc@thread.tacv2"], equal_to("ops"))
    assert_that(channels[_TEAM_ID], none())


@patch("api.infrastructure.msteams.client.resilient_request")
def test_two_connections_never_share_a_cached_channel_name(mock_request) -> None:
    first_response = MagicMock(status_code=200)
    first_response.json.return_value = {"conversations": [{"id": "19:abc@thread.tacv2", "name": "one"}]}
    second_response = MagicMock(status_code=200)
    second_response.json.return_value = {"conversations": [{"id": "19:abc@thread.tacv2", "name": "two"}]}
    mock_request.side_effect = [first_response, second_response]

    first = list_team_channels(_SERVICE_URL, _TEAM_ID, "bot-token-one")
    second = list_team_channels(_SERVICE_URL, _TEAM_ID, "bot-token-two")

    assert_that(first["19:abc@thread.tacv2"], equal_to("one"))
    assert_that(second["19:abc@thread.tacv2"], equal_to("two"))


@patch("api.infrastructure.msteams.client.resilient_request")
def test_send_activity_carries_the_provider_idempotency_key(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "activity-1"}
    mock_request.return_value = response

    activity_id = send_activity(
        _SERVICE_URL,
        "conversation-1",
        {"type": "message", "text": "reply"},
        "access-value",
        idempotency_key="provider-key",
    )

    assert_that(activity_id, equal_to("activity-1"))
    assert_that(mock_request.call_args.kwargs["headers"]["Idempotency-Key"], equal_to("provider-key"))
    assert_that(json.loads(mock_request.call_args.kwargs["content"])["text"], equal_to("reply"))


@pytest.mark.parametrize("body", [{}, {"id": "   "}])
@patch("api.infrastructure.msteams.client.resilient_request")
def test_send_activity_rejects_a_success_without_an_activity_id(mock_request, body):
    response = MagicMock(status_code=200)
    response.json.return_value = body
    mock_request.return_value = response

    with pytest.raises(TeamsDeliveryError, match="no activity id"):
        send_activity(
            _SERVICE_URL,
            "conversation-1",
            {"type": "message", "text": "reply"},
            "access-value",
        )
