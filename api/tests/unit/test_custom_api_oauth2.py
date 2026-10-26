"""OAuth2 client-credentials connections: the gateway's token cache and the pod boundary."""

import json
from typing import cast
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length

from api.domains.custom_api import request as engine
from api.domains.custom_api.gateway import TOKEN_EXPIRY_MARGIN, AccessTokenCache
from api.domains.custom_api.models import CustomApiConnection
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.runtime import materialize_custom_api
from api.infrastructure.crypto import encrypt_token
from api.tests.steps.agent import TEST_ENCRYPTION_KEY as _KEY

_AUTH = {
    "type": "oauth2_client_credentials",
    "token_url": "https://auth.example.com/oauth/token",
    "client_id": "fixture-client-id",
    "client_secret": "fixture-client-secret",
}


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def _cache(monkeypatch, lifetime=3600):
    exchanges: list[dict] = []

    def exchange(auth):
        exchanges.append(auth)
        return f"minted-{len(exchanges)}", lifetime

    monkeypatch.setattr(engine, "fetch_access_token", exchange)
    cache = AccessTokenCache()
    clock = Clock()
    cache._clock = clock
    return cache, clock, exchanges


def test_cache_serves_one_exchange_per_connection_until_the_lifetime_nears_its_end(monkeypatch):
    cache, clock, exchanges = _cache(monkeypatch)
    connection = uuid4()
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to("minted-1"))
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to("minted-1"))
    assert_that(cache.access_token(uuid4(), "rev-1", _AUTH), equal_to("minted-2"))
    clock.now += 3600 - TOKEN_EXPIRY_MARGIN - 1
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to("minted-1"))
    clock.now += 2
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to("minted-3"))
    assert_that(exchanges, has_length(3))


def test_new_client_credentials_replace_the_cached_token_without_a_restart(monkeypatch):
    cache, _, exchanges = _cache(monkeypatch)
    connection = uuid4()
    cache.access_token(connection, "rev-1", _AUTH)
    rotated = {**_AUTH, "client_secret": "rotated-secret"}
    assert_that(cache.access_token(connection, "rev-2", rotated), equal_to("minted-2"))
    assert_that(exchanges[-1]["client_secret"], equal_to("rotated-secret"))


def test_a_token_the_upstream_rejected_is_discarded_but_a_newer_one_is_kept(monkeypatch):
    cache, _, _ = _cache(monkeypatch)
    connection = uuid4()
    first = cache.access_token(connection, "rev-1", _AUTH)
    cache.discard(connection, "some-other-token")
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to(first))
    cache.discard(connection, first)
    assert_that(cache.access_token(connection, "rev-1", _AUTH), equal_to("minted-2"))


def test_a_short_lived_token_is_exchanged_on_every_request(monkeypatch):
    cache, _, exchanges = _cache(monkeypatch, lifetime=TOKEN_EXPIRY_MARGIN)
    connection = uuid4()
    cache.access_token(connection, "rev-1", _AUTH)
    cache.access_token(connection, "rev-1", _AUTH)
    assert_that(exchanges, has_length(2))


def _row(isolated: bool) -> CustomApiConnection:
    config = {"auth": _AUTH, "headers": []}
    return CustomApiConnection(
        agent_id=uuid4(),
        slug="snovio",
        name="Snov.io",
        base_url="https://api.snov.io",
        isolated=isolated,
        credentials_encrypted=encrypt_token(json.dumps(config), _KEY),
    )


def test_direct_materialization_of_client_credentials_is_refused():
    with pytest.raises(ValueError, match="isolation"):
        materialize_custom_api(
            [_row(isolated=False)], _KEY, "http://gateway.test", repository=cast(CustomApiRepository, None)
        )


def test_isolated_materialization_hands_the_pod_only_a_gateway_profile():
    artifacts = materialize_custom_api(
        [_row(isolated=True)], _KEY, "http://gateway.test", repository=cast(CustomApiRepository, None)
    )
    profile = artifacts.files["custom-api-profiles.toml"]
    assert_that(profile, contains_string('provider = "custom_api"'))
    assert_that(profile, contains_string('auth_type = "none"'))
    assert_that(profile, contains_string('gateway_url = "http://gateway.test/custom-api/request"'))
    materialized = json.dumps([profile, artifacts.files["custom-api-setup.sh"], artifacts.policy_md, artifacts.env])
    for secret in ("fixture-client-secret", "fixture-client-id", "auth.example.com"):
        assert secret not in materialized, secret
