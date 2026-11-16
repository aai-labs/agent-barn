"""The credential gateway's MCP route, against a fake MCP server.

The contract under test:

- only a token issued to the Agent's current, running generation is accepted, and the Agent
  and Organization come from that token alone;
- the server named in the path is reached only while that Agent may use it, so disabling,
  detaching or deleting it takes effect on the next request, with a readable refusal;
- the pod's token never reaches the server: the server's own credential replaces it, and a
  credential the server echoes back is redacted;
- the tool filter is the gateway's: hidden tools are left out of `tools/list` and refused on
  `tools/call` before the server is contacted;
- the server-to-client GET stream is not offered, batches are refused, and redirects are
  not followed.
"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_length,
    is_not,
)

from api.domains.agents.models import AgentStatus
from api.domains.integrations.repository import IntegrationRepository
from api.domains.mcp_servers import gateway as gateway_module
from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.broker import NEEDS_SIGN_IN, SIGN_IN_EXPIRED
from api.domains.mcp_servers.gateway import UNAVAILABLE
from api.domains.mcp_servers.models import (
    AgentMcpServerAttachment,
    McpServerCredential,
    McpServerScope,
    OrganizationMcpServer,
)
from api.domains.mcp_servers.repository import McpServerRepository
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.public_http import PinnedRequest
from api.tests.core.givenpy import LambdaWith, given, then, when
from api.tests.core.modules import prepare_gateway_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

POD_TOKEN = "pod-gateway-token"
SERVER_TOKEN = "server-secret-token"
_MCP = "/gateway/v1/mcp"


def _lower(headers) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


class FakeMcpServer:
    """A Streamable HTTP MCP server on loopback that records what reached it."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                pass

            def _send(self, status_code: int, body: bytes = b"", content_type: str = "application/json", **headers):
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_DELETE(self):
                fake.requests.append({"method": "DELETE", "headers": _lower(self.headers), "body": None})
                self._send(200)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                message = json.loads(raw)
                fake.requests.append({"method": "POST", "headers": _lower(self.headers), "body": message})
                if self.path == "/redirect":
                    return self._send(302, Location="https://elsewhere.example.com/mcp")
                if self.headers.get("Authorization") == "Bearer stale-access":
                    return self._send(401, b'{"error":"invalid_token"}')
                method, rid = message.get("method"), message.get("id")
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake"},
                    }
                    body = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
                    return self._send(200, body, **{"Mcp-Session-Id": "upstream-session"})
                if rid is None:
                    return self._send(202)
                if method == "tools/list":
                    tools = [{"name": "search"}, {"name": "delete_all"}]
                    event = json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}})
                    return self._send(200, f"event: message\ndata: {event}\n\n".encode(), "text/event-stream")
                # tools/call: echo the credential it received, as a careless server might.
                text = f"called {message['params']['name']} with {self.headers.get('Authorization')}"
                event = json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}}
                )
                self._send(200, f"event: message\ndata: {event}\n\n".encode(), "text/event-stream")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_port

    def calls(self, method: str) -> list[dict]:
        return [r for r in self.requests if r["body"] and r["body"].get("method") == method]


def fake_server_is_running():
    def step(context):
        context.upstream = FakeMcpServer()
        thread = threading.Thread(target=context.upstream.httpd.serve_forever, daemon=True)

        def pin(url: str) -> PinnedRequest:
            # The real check refuses loopback; here every server is the fake one, keeping its path.
            path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
            return PinnedRequest(url=f"http://127.0.0.1:{context.upstream.port}{path}")

        patcher = patch.object(gateway_module, "pin_to_public_address", pin)

        def start():
            patcher.start()
            thread.start()

        def stop():
            patcher.stop()
            context.upstream.httpd.shutdown()
            context.upstream.httpd.server_close()

        return LambdaWith(start, stop)

    return step


def _server(
    context, identifier: str = "linear", *, organization_id: UUID | None = None, **fields
) -> OrganizationMcpServer:
    credentials = {"auth": {"type": "bearer", "token": SERVER_TOKEN}, "headers": []}
    server = OrganizationMcpServer(
        organization_id=organization_id or context.organization.id,
        identifier=identifier,
        name=identifier.title(),
        url=fields.pop("url", "https://mcp.example.com/mcp"),
        scope=fields.pop("scope", McpServerScope.ALL_AGENTS.value),
        credentials_encrypted=encrypt_token(json.dumps(credentials), TEST_ENCRYPTION_KEY),
        **fields,
    )
    context.injector.get(PostgresRepositoryDelegate).save(server)
    return server


def agent_runs_with_a_gateway_token():
    def step(context):
        context.generation = context.injector.get(IntegrationRepository).begin(context.agent.id, {}).generation
        context.injector.get(McpServerRepository).set_gateway_token(
            context.agent.id,
            context.agent.organization_id,
            hashlib.sha256(POD_TOKEN.encode()).hexdigest(),
            context.generation,
        )

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_gateway_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization(),
    there_is_an_agent(status=AgentStatus.RUNNING),
    agent_runs_with_a_gateway_token(),
    fake_server_is_running(),
]


def _post(context, message: dict | list, identifier: str = "linear", token: str = POD_TOKEN, **headers):
    return context.gateway_client.post(
        f"{_MCP}/{identifier}", json=message, headers={"Authorization": f"Bearer {token}", **headers}
    )


def _rpc(method: str, request_id: int | None = 1, **params) -> dict:
    message: dict = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params:
        message["params"] = params
    return message


def _sse_result(response) -> dict:
    data = next(line for line in response.text.splitlines() if line.startswith("data:"))
    return json.loads(data.removeprefix("data:").strip())


# --- relaying -------------------------------------------------------------------


def test_the_server_gets_its_own_credential_and_never_the_pods_token():
    with given(_GIVEN) as context:
        _server(context)

        with when("the Agent initializes the server through the gateway"):
            response = _post(context, _rpc("initialize", protocolVersion="2025-11-25"))

        with then("the answer and the server's session id come back"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.headers["mcp-session-id"], equal_to("upstream-session"))
            assert_that(response.json()["result"]["serverInfo"], equal_to({"name": "fake"}))

        with then("the server saw its own token, not the pod's"):
            headers = context.upstream.calls("initialize")[0]["headers"]
            assert_that(headers["authorization"], equal_to(f"Bearer {SERVER_TOKEN}"))
            assert_that(json.dumps(headers), is_not(contains_string(POD_TOKEN)))


def test_the_session_and_protocol_headers_reach_the_server():
    with given(_GIVEN) as context:
        _server(context)

        _post(
            context,
            _rpc("notifications/initialized", None),
            **{"Mcp-Session-Id": "upstream-session", "MCP-Protocol-Version": "2025-11-25"},
        )

        headers = context.upstream.calls("notifications/initialized")[0]["headers"]
        assert_that(headers, has_entries({"mcp-session-id": "upstream-session", "mcp-protocol-version": "2025-11-25"}))


def test_hidden_tools_are_left_out_of_the_tool_list():
    with given(_GIVEN) as context:
        _server(context, tool_exclude=["delete_all"])

        response = _post(context, _rpc("tools/list"))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that([t["name"] for t in _sse_result(response)["result"]["tools"]], contains_exactly("search"))


def test_a_hidden_tool_is_refused_without_contacting_the_server():
    with given(_GIVEN) as context:
        _server(context, tool_include=["search"])

        with when("the Agent calls a tool the include list leaves out"):
            response = _post(context, _rpc("tools/call", name="delete_all", arguments={}))

        with then("it gets a JSON-RPC error and the server never hears of it"):
            assert_that(response.json(), has_entries(id=1, error=has_entries(message="Tool not available")))
            assert_that(context.upstream.calls("tools/call"), empty())


def test_a_credential_the_server_echoes_is_redacted():
    with given(_GIVEN) as context:
        _server(context)

        response = _post(context, _rpc("tools/call", name="search", arguments={}))

        text = _sse_result(response)["result"]["content"][0]["text"]
        # The whole Authorization value is a secret, so the scheme goes with the token.
        assert_that(text, equal_to("called search with [REDACTED]"))


# --- what the gateway refuses ------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_the_server_to_client_stream_is_not_offered(method: str):
    with given(_GIVEN) as context:
        _server(context)

        response = context.gateway_client.request(
            method, f"{_MCP}/linear", headers={"Authorization": f"Bearer {POD_TOKEN}"}
        )

        assert_that(response.status_code, equal_to(status.HTTP_405_METHOD_NOT_ALLOWED))
        assert_that(context.upstream.requests, empty())


def test_a_batch_is_refused():
    with given(_GIVEN) as context:
        _server(context)

        response = _post(context, [_rpc("tools/list", 1), _rpc("tools/list", 2)])

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(context.upstream.requests, empty())


def test_a_redirect_is_not_followed():
    with given(_GIVEN) as context:
        _server(context, url="https://mcp.example.com/redirect")

        response = _post(context, _rpc("initialize"))

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))


def test_an_unknown_token_is_refused_opaquely():
    with given(_GIVEN) as context:
        _server(context)

        response = _post(context, _rpc("initialize"), token="not-issued")

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.text, is_not(contains_string(UNAVAILABLE)))
        assert_that(context.upstream.requests, empty())


def test_a_token_from_an_earlier_generation_is_refused():
    with given(_GIVEN) as context:
        _server(context)
        context.injector.get(IntegrationRepository).begin(context.agent.id, {})

        response = _post(context, _rpc("initialize"))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_stopped_agents_token_is_refused():
    with given(_GIVEN) as context:
        _server(context)
        context.agent.status = AgentStatus.STOPPED
        context.injector.get(PostgresRepositoryDelegate).save(context.agent)

        response = _post(context, _rpc("initialize"))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- removal takes effect at once ---------------------------------------------------


def test_a_disabled_server_answers_that_it_is_no_longer_available():
    with given(_GIVEN) as context:
        _server(context, enabled=False)

        with when("the Agent calls a tool on a server its Organization disabled"):
            response = _post(context, _rpc("tools/call", name="search", arguments={}))

        with then("the answer says so in words the model can act on, and nothing is forwarded"):
            assert_that(response.json(), has_entries(id=1, error=has_entries(message=UNAVAILABLE)))
            assert_that(context.upstream.requests, empty())


def test_a_selected_agents_server_needs_the_agents_attachment():
    with given(_GIVEN) as context:
        server = _server(context, scope=McpServerScope.SELECTED_AGENTS.value)

        with when("the Agent is not attached, then attached"):
            refused = _post(context, _rpc("initialize"))
            context.injector.get(PostgresRepositoryDelegate).save(
                AgentMcpServerAttachment(
                    organization_id=context.organization.id, agent_id=context.agent.id, mcp_server_id=server.id
                )
            )
            allowed = _post(context, _rpc("initialize"))

        with then("only the attached Agent reaches it"):
            assert_that(refused.json(), has_entries(error=has_entries(message=UNAVAILABLE)))
            assert_that(allowed.json(), has_entries(result=has_entries(protocolVersion="2025-11-25")))
            assert_that(context.upstream.calls("initialize"), has_length(1))


def test_a_notification_to_an_unavailable_server_is_refused():
    with given(_GIVEN) as context:
        _server(context, enabled=False)

        response = _post(context, _rpc("notifications/initialized", None))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.json(), equal_to({"error": UNAVAILABLE}))


def test_another_organizations_server_is_never_reached():
    with given(_GIVEN) as context:
        mine = context.organization
        theirs = uuid7()
        there_is_an_organization(id=theirs, name="Other")(context)
        context.organization = mine
        _server(context, "shared-name", organization_id=theirs)

        response = _post(context, _rpc("initialize"), identifier="shared-name")

        assert_that(response.json(), has_entries(error=has_entries(message=UNAVAILABLE)))
        assert_that(context.upstream.requests, empty())


# --- Agent servers ------------------------------------------------------------------


def test_an_agent_server_is_reached_by_its_own_agent_only():
    with given(_GIVEN) as context:
        mine = context.agent
        there_is_an_agent(name="Other Agent")(context)
        other = context.agent
        context.agent = mine
        _server(context, "own", scope=McpServerScope.AGENT.value, agent_id=mine.id)
        _server(context, "theirs", scope=McpServerScope.AGENT.value, agent_id=other.id)

        with when("the Agent calls its own server, then another Agent's"):
            own = _post(context, _rpc("initialize"), identifier="own")
            theirs = _post(context, _rpc("initialize"), identifier="theirs")

        with then("only its own reaches a server, with the server's credential"):
            assert_that(own.json(), has_entries(result=has_entries(protocolVersion="2025-11-25")))
            assert_that(theirs.json(), has_entries(error=has_entries(message=UNAVAILABLE)))
            assert_that(context.upstream.calls("initialize"), has_length(1))
            assert_that(context.upstream.requests[0]["headers"]["authorization"], equal_to(f"Bearer {SERVER_TOKEN}"))


def test_an_organization_server_wins_over_an_agent_server_of_the_same_name():
    with given(_GIVEN) as context:
        _server(context, "linear", scope=McpServerScope.AGENT.value, agent_id=context.agent.id, url="https://agent/mcp")
        _server(context, "linear", url="https://organization/mcp")

        effective = context.injector.get(McpServerRepository).effective_for_agent(context.agent.id)

        assert_that([(s.identifier, s.url) for s in effective], equal_to([("linear", "https://organization/mcp")]))


# --- OAuth sign-ins and Agent credentials -----------------------------------------------

_OAUTH = {
    "type": "oauth",
    "resource": "https://mcp.example.com/mcp",
    "issuer": "https://auth.example.com",
    "authorization_endpoint": "https://auth.example.com/authorize",
    "token_endpoint": "https://auth.example.com/token",
    "scope": "read",
    "client_id": "client-1",
    "client_secret": None,
    "token_endpoint_auth_method": "none",
    "registered": True,
}


def _oauth_server(context) -> OrganizationMcpServer:
    server = OrganizationMcpServer(
        organization_id=context.organization.id,
        identifier="notion",
        name="Notion",
        url="https://mcp.example.com/mcp",
        scope=McpServerScope.ALL_AGENTS.value,
        credentials_encrypted=encrypt_token(json.dumps({"auth": _OAUTH, "headers": []}), TEST_ENCRYPTION_KEY),
    )
    context.injector.get(PostgresRepositoryDelegate).save(server)
    return server


def _hold(context, server, *, agent_id=None, kind="oauth", content: dict, status_value="active") -> McpServerCredential:
    row = McpServerCredential(
        organization_id=context.organization.id,
        mcp_server_id=server.id,
        agent_id=agent_id,
        kind=kind,
        status=status_value,
        credentials_encrypted=encrypt_token(json.dumps(content), TEST_ENCRYPTION_KEY),
    )
    context.injector.get(PostgresRepositoryDelegate).save(row)
    return row


def _grant(access: str, *, expires_at: float = 9_999_999_999.0, refresh: str | None = "refresh-1") -> dict:
    return {"access_token": access, "refresh_token": refresh, "expires_at": expires_at, "scope": "read"}


def _stored(context, row: McpServerCredential) -> tuple[str, dict]:
    fresh = context.injector.get(PostgresRepositoryDelegate).find_by_id(McpServerCredential, row.id)
    return fresh.status, json.loads(decrypt_token(fresh.credentials_encrypted, TEST_ENCRYPTION_KEY))


def test_the_organization_sign_in_reaches_the_server_as_a_bearer_token():
    with given(_GIVEN) as context:
        server = _oauth_server(context)
        _hold(context, server, content=_grant("org-access"))

        _post(context, _rpc("initialize"), identifier="notion")

        assert_that(context.upstream.calls("initialize")[0]["headers"]["authorization"], equal_to("Bearer org-access"))


def test_an_expired_access_token_is_refreshed_and_the_rotated_grant_kept(monkeypatch):
    with given(_GIVEN) as context:
        server = _oauth_server(context)
        row = _hold(context, server, content=_grant("old-access", expires_at=0))
        monkeypatch.setattr(
            oauth,
            "refresh",
            lambda config, refresh_token: oauth.TokenSet("new-access", "refresh-2", 9_999_999_999.0, "read"),
        )

        with when("the Agent calls the server after its access token expired"):
            _post(context, _rpc("initialize"), identifier="notion")

        with then("the server got the refreshed token and the rotated refresh token is stored"):
            assert_that(
                context.upstream.calls("initialize")[0]["headers"]["authorization"], equal_to("Bearer new-access")
            )
            status_value, grant = _stored(context, row)
            assert_that(
                (status_value, grant["refresh_token"], grant["access_token"]),
                equal_to(("active", "refresh-2", "new-access")),
            )


def test_a_refused_refresh_asks_for_a_new_sign_in(monkeypatch):
    def refused(config, refresh_token):
        raise oauth.OAuthRefused("invalid_grant")

    with given(_GIVEN) as context:
        server = _oauth_server(context)
        row = _hold(context, server, content=_grant("old-access", expires_at=0))
        monkeypatch.setattr(oauth, "refresh", refused)

        with when("the grant was revoked at the authorization server"):
            response = _post(context, _rpc("tools/list"), identifier="notion")

        with then("the Agent is told to sign in again, the server is not contacted, and the mark sticks"):
            assert_that(response.json(), has_entries(error=has_entries(message=SIGN_IN_EXPIRED)))
            assert_that(context.upstream.requests, empty())
            assert_that(_stored(context, row)[0], equal_to("needs_sign_in"))


def test_an_oauth_server_nobody_signed_in_to_is_not_usable():
    with given(_GIVEN) as context:
        _oauth_server(context)

        response = _post(context, _rpc("initialize"), identifier="notion")

        assert_that(response.json(), has_entries(error=has_entries(message=NEEDS_SIGN_IN)))
        assert_that(context.upstream.requests, empty())


def test_the_agents_own_sign_in_wins_over_the_organizations():
    with given(_GIVEN) as context:
        server = _oauth_server(context)
        _hold(context, server, content=_grant("org-access"))
        _hold(context, server, agent_id=context.agent.id, content=_grant("agent-access"))

        _post(context, _rpc("initialize"), identifier="notion")

        assert_that(
            context.upstream.calls("initialize")[0]["headers"]["authorization"], equal_to("Bearer agent-access")
        )


def test_the_agents_own_token_wins_over_the_servers():
    with given(_GIVEN) as context:
        server = _server(context)
        _hold(
            context,
            server,
            agent_id=context.agent.id,
            kind="static",
            content={"auth": {"type": "bearer", "token": "agent-token"}, "headers": []},
        )

        _post(context, _rpc("initialize"))

        assert_that(context.upstream.calls("initialize")[0]["headers"]["authorization"], equal_to("Bearer agent-token"))


def test_an_access_token_the_server_refuses_is_retired():
    with given(_GIVEN) as context:
        server = _oauth_server(context)
        row = _hold(context, server, content=_grant("stale-access"))

        response = _post(context, _rpc("initialize"), identifier="notion")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        assert_that(_stored(context, row)[1]["expires_at"], equal_to(0))
