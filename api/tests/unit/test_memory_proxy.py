"""The memory proxy forwards an Agent's own-pool requests to Honcho (AF-338)."""

import uuid
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from hamcrest import assert_that, equal_to, has_entries

from api.core.config import Config
from api.domains.agents.memory_access import MemoryAccessDenied, MemoryKeyRejected
from api.domains.memory_proxy.proxy import MemoryProxy
from api.memory_proxy_app import create_memory_proxy_app

AGENT = uuid.uuid4()
WS = "af-pool-0199"
SECRET = "a-test-jwt-secret-at-least-32-bytes-long"
KEY = "memory-key"


def config(**values):
    return Config.model_validate(
        {
            "db_connection_url": "postgresql://test:test@localhost/test",
            "secret_signing_key": "test",
            "platform_admin_credentials": "test:test",
            "organization_default_llm_budget_usd": 100,
            "agent_default_llm_budget_usd": 10,
            "honcho_base_url": "http://honcho:8000",
            "honcho_jwt_secret": SECRET,
            **values,
        }
    )


class _Chunks(httpx.AsyncByteStream):
    """A body that arrives as a stream, as it does from a real Honcho."""

    def __init__(self, *chunks: bytes):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


class Upstream:
    """A stand-in Honcho that records what reached it."""

    def __init__(self, status=200, *, headers=None, chunks=(b'{"content":"remembered"}',)):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        self.chunks = chunks

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, headers=self.headers, stream=_Chunks(*self.chunks))


def proxy_client(upstream: Upstream, *, authorize=None, **config_values) -> TestClient:
    access = MagicMock()
    access.authorize.side_effect = authorize or (lambda agent_id, key: WS if key == KEY else _reject())
    proxy = MemoryProxy(
        access=access,
        config=config(**config_values),
        transport=httpx.MockTransport(upstream),
    )
    return TestClient(create_memory_proxy_app(proxy=proxy))


def _reject():
    raise MemoryKeyRejected


def bearer(key=KEY):
    return {"Authorization": f"Bearer {key}"}


def test_an_agents_own_pool_request_is_forwarded_with_a_pool_scoped_token():
    upstream = Upstream()
    client = proxy_client(upstream)

    response = client.post(f"/agents/{AGENT}/v3/workspaces/{WS}/chat?x=1", json={"query": "hi"}, headers=bearer())

    assert_that(response.status_code, equal_to(200))
    assert_that(response.json(), equal_to({"content": "remembered"}))
    sent = upstream.requests[0]
    assert_that(str(sent.url), equal_to(f"http://honcho:8000/v3/workspaces/{WS}/chat?x=1"))
    assert_that(sent.content, equal_to(b'{"query":"hi"}'))
    token = sent.headers["authorization"].removeprefix("Bearer ")
    assert_that(jwt.decode(token, SECRET, algorithms=["HS256"]), has_entries({"w": WS}))


def test_the_agents_own_key_never_reaches_honcho():
    upstream = Upstream()
    proxy_client(upstream).get(f"/agents/{AGENT}/v3/workspaces/{WS}", headers=bearer())
    assert_that(KEY in upstream.requests[0].headers["authorization"], equal_to(False))


def test_with_honcho_auth_off_nothing_is_signed():
    """Local development runs Honcho without auth; there is no secret to sign with."""
    upstream = Upstream()
    proxy_client(upstream, honcho_jwt_secret="").get(f"/agents/{AGENT}/v3/workspaces/{WS}", headers=bearer())
    assert_that("authorization" in upstream.requests[0].headers, equal_to(False))


def test_a_streamed_answer_is_passed_through():
    upstream = Upstream(headers={"content-type": "text/event-stream"}, chunks=(b"data: a\n\n", b"data: b\n\n"))
    response = proxy_client(upstream).post(f"/agents/{AGENT}/v3/workspaces/{WS}/chat", json={}, headers=bearer())
    assert_that(response.headers["content-type"], equal_to("text/event-stream"))
    assert_that(response.content, equal_to(b"data: a\n\ndata: b\n\n"))


def test_honchos_own_errors_reach_the_runtime_unchanged():
    upstream = Upstream(404, chunks=(b'{"detail":"Peer not found"}',))
    response = proxy_client(upstream).get(f"/agents/{AGENT}/v3/workspaces/{WS}/peers/x", headers=bearer())
    assert_that((response.status_code, response.json()), equal_to((404, {"detail": "Peer not found"})))


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic x"}])
def test_a_caller_without_the_agents_key_is_turned_away_before_honcho(headers):
    upstream = Upstream()
    response = proxy_client(upstream).get(f"/agents/{AGENT}/v3/workspaces/{WS}", headers=headers)
    assert_that((response.status_code, upstream.requests), equal_to((401, [])))


def test_an_agent_whose_memory_is_off_is_refused_before_honcho():
    upstream = Upstream()

    def denied(agent_id, key):
        raise MemoryAccessDenied

    response = proxy_client(upstream, authorize=denied).get(f"/agents/{AGENT}/v3/workspaces/{WS}", headers=bearer())
    assert_that((response.status_code, upstream.requests), equal_to((403, [])))


def test_a_request_outside_the_agents_rights_is_refused_before_honcho():
    upstream = Upstream()
    response = proxy_client(upstream).put(
        f"/agents/{AGENT}/v3/workspaces/{WS}", json={"configuration": {}}, headers=bearer()
    )
    assert_that((response.status_code, upstream.requests), equal_to((403, [])))


def test_an_unreachable_honcho_is_a_bad_gateway():
    def down(request):
        raise httpx.ConnectError("refused")

    access = MagicMock()
    access.authorize.return_value = WS
    proxy = MemoryProxy(access=access, config=config(), transport=httpx.MockTransport(down))
    response = TestClient(create_memory_proxy_app(proxy=proxy)).get(
        f"/agents/{AGENT}/v3/workspaces/{WS}", headers=bearer()
    )
    assert_that(response.status_code, equal_to(502))


def test_a_malformed_agent_id_is_not_found():
    response = proxy_client(Upstream()).get("/agents/not-a-uuid/v3/workspaces", headers=bearer())
    assert_that(response.status_code, equal_to(404))


def test_the_proxy_reports_its_own_health_without_a_key():
    assert_that(proxy_client(Upstream()).get("/health").status_code, equal_to(200))
