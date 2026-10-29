import time

from hamcrest import assert_that, calling, equal_to, raises

from api.domains.agents.microsoft_identity import (
    MicrosoftAppTokens,
    MicrosoftIdentityClient,
    MicrosoftIdentityUnavailable,
    MicrosoftTokens,
)


class _Identity(MicrosoftIdentityClient):
    def __init__(self, *results: MicrosoftTokens | Exception):
        self.results = list(results)
        self.calls: list[dict] = []

    def client_credentials(self, *, tenant_id: str, client_id: str, client_secret: str) -> MicrosoftTokens:
        self.calls.append({"tenant_id": tenant_id, "client_id": client_id, "client_secret": client_secret})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _tokens(access_token: str, expires_in: int = 3599) -> MicrosoftTokens:
    return MicrosoftTokens(
        access_token=access_token, refresh_token=None, expires_in=expires_in, scope="", id_token=None
    )


def test_a_token_is_fetched_once_and_reused_until_near_expiry():
    identity, clock = _Identity(_tokens("first"), _tokens("second")), _Clock()
    tokens = MicrosoftAppTokens(identity, clock=clock)

    first = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")
    clock.now += 3599 - 301
    reused = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")
    clock.now += 2
    refreshed = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")

    assert_that((first, reused, refreshed), equal_to(("first", "first", "second")))
    assert_that(
        identity.calls,
        equal_to([{"tenant_id": "tenant-1", "client_id": "app", "client_secret": "secret"}] * 2),
    )


def test_each_tenant_has_its_own_token():
    identity = _Identity(_tokens("one"), _tokens("two"))
    tokens = MicrosoftAppTokens(identity, clock=_Clock())

    one = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")
    two = tokens.get(tenant_id="tenant-2", client_id="app", client_secret="secret")

    assert_that((one, two), equal_to(("one", "two")))


def test_a_failed_fetch_is_not_remembered():
    identity = _Identity(MicrosoftIdentityUnavailable("ConnectError"), _tokens("later"))
    tokens = MicrosoftAppTokens(identity, clock=_Clock())

    assert_that(
        calling(tokens.get).with_args(tenant_id="tenant-1", client_id="app", client_secret="secret"),
        raises(MicrosoftIdentityUnavailable),
    )
    assert_that(tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret"), equal_to("later"))


def test_expiry_is_measured_on_the_wall_clock_so_a_sleeping_host_refetches(monkeypatch):
    identity = _Identity(_tokens("before sleep"), _tokens("after sleep"))
    wall = [time.time()]
    monkeypatch.setattr(time, "time", lambda: wall[0])
    tokens = MicrosoftAppTokens(identity)
    first = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")
    wall[0] += 3600

    after = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")

    assert_that((first, after), equal_to(("before sleep", "after sleep")))


def test_an_evicted_token_is_fetched_again():
    identity = _Identity(_tokens("rejected"), _tokens("fresh"))
    tokens = MicrosoftAppTokens(identity, clock=_Clock())
    first = tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")

    tokens.evict(tenant_id="TENANT-1", client_id="app")

    assert_that(
        (first, tokens.get(tenant_id="tenant-1", client_id="app", client_secret="secret")),
        equal_to(("rejected", "fresh")),
    )
