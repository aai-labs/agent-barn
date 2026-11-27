"""The save-time MCP probe: Streamable HTTP as Hermes and OpenClaw speak it, under the
Custom API destination policy, and what it tells an Admin about the server's tools."""

import json
from collections.abc import Callable

import pytest
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_item,
    has_length,
    is_,
    is_not,
)

from api.domains.custom_api.request import RequestRefused
from api.domains.mcp_servers import probe as probe_module
from api.domains.mcp_servers.probe import (
    McpProbeError,
    McpServerProbe,
    ProbedTool,
    ProbeResult,
    analyse_tools,
)
from api.tests.core.givenpy import given, then, when

_URL = "https://mcp.example.com/mcp"
_BEARER = {"auth": {"type": "bearer", "token": "secret-token"}, "headers": []}


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self._headers = headers or {}

    def read(self, limit: int) -> bytes:
        return self._body[:limit]

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers.items())


class FakeServer:
    """Answers each request in turn and records method, path, headers and body."""

    def __init__(self, answer: Callable[[str, dict | None, dict], FakeResponse]) -> None:
        self.answer = answer
        self.requests: list[dict] = []
        self.connected: list[tuple[str, str, int]] = []

    def connect(self, host: str, address: str, port: int):
        self.connected.append((host, address, port))
        server = self

        class Connection:
            def request(self, method, path, body=None, headers=None):
                payload = json.loads(body) if body else None
                server.requests.append({"method": method, "path": path, "headers": headers or {}, "body": payload})
                self.response = server.answer(method, payload, headers or {})

            def getresponse(self):
                return self.response

            def close(self):
                pass

        return Connection()


def _json(message: dict, **headers: str) -> FakeResponse:
    return FakeResponse(200, json.dumps(message).encode(), {"Content-Type": "application/json", **headers})


def _sse(*messages: dict) -> FakeResponse:
    body = "".join(f"event: message\ndata: {json.dumps(m)}\n\n" for m in messages).encode()
    return FakeResponse(200, body, {"Content-Type": "text/event-stream"})


def _well_behaved(tool_pages: list[list[str]] | None = None) -> Callable[[str, dict | None, dict], FakeResponse]:
    pages = tool_pages or [["search", "create"]]

    def answer(method: str, body: dict | None, headers: dict) -> FakeResponse:
        if method == "DELETE" or body is None:
            return FakeResponse(200)
        if body["method"] == "initialize":
            return _json(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "9"},
                    },
                },
                **{"Mcp-Session-Id": "session-1"},
            )
        if body["method"] == "notifications/initialized":
            return FakeResponse(202)
        index = int(body["params"].get("cursor", "0"))
        result: dict = {"tools": [{"name": name, "description": f"{name} tool"} for name in pages[index]]}
        if index + 1 < len(pages):
            result["nextCursor"] = str(index + 1)
        # A log notification ahead of the answer, as Streamable HTTP servers may send.
        return _sse(
            {"jsonrpc": "2.0", "method": "notifications/message", "params": {}},
            {"jsonrpc": "2.0", "id": body["id"], "result": result},
        )

    return answer


def _server_is(answer: Callable[[str, dict | None, dict], FakeResponse]):
    def step(context):
        context.server = FakeServer(answer)
        context.probe = McpServerProbe()
        context.probe.connect = context.server.connect

    return step


def _public_dns(monkeypatch):
    def step(context):
        monkeypatch.setattr(probe_module, "public_addresses", lambda host, port: ["203.0.113.7"])

    return step


def test_a_server_is_initialized_and_its_paged_tools_listed(monkeypatch):
    with given([_public_dns(monkeypatch), _server_is(_well_behaved([["search", "create"], ["delete"]]))]) as context:
        with when("the probe connects with a bearer token"):
            result = context.probe.probe(_URL, _BEARER)

        with then("it reports the server and every page of tools"):
            assert_that(result.server_name, equal_to("fake"))
            assert_that(result.protocol_version, equal_to("2025-11-25"))
            assert_that([tool.name for tool in result.tools], contains_exactly("search", "create", "delete"))

        with then("it pins the checked address and keeps TLS on the configured host"):
            assert_that(context.server.connected[0], equal_to(("mcp.example.com", "203.0.113.7", 443)))

        with then("every request carries the credential; later ones the session and protocol"):
            first, *rest = context.server.requests
            assert_that(
                first["headers"],
                has_entries({"authorization": "Bearer secret-token", "user-agent": "agent-barn-mcp-probe/1"}),
            )
            assert_that(first["headers"].get("mcp-session-id"), is_(None))
            for request in rest:
                assert_that(
                    request["headers"],
                    has_entries({"mcp-session-id": "session-1", "mcp-protocol-version": "2025-11-25"}),
                )

        with then("the session is ended"):
            assert_that(context.server.requests[-1]["method"], equal_to("DELETE"))


def test_a_refused_credential_is_reported_as_refused(monkeypatch):
    with given([_public_dns(monkeypatch), _server_is(lambda method, body, headers: FakeResponse(401))]) as context:
        with pytest.raises(McpProbeError) as raised:
            context.probe.probe(_URL, _BEARER)

        assert_that(raised.value.refused, is_(True))
        assert_that(str(raised.value), contains_string("HTTP 401"))


_OAUTH_CHALLENGE = {
    "WWW-Authenticate": (
        'Bearer error="invalid_request", error_description="No access token was provided in this request", '
        'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"'
    )
}
_NONE = {"auth": {"type": "none"}, "headers": []}


def _refused_with(monkeypatch, response: FakeResponse, config: dict) -> McpProbeError:
    with given([_public_dns(monkeypatch), _server_is(lambda method, body, headers: response)]) as context:
        with pytest.raises(McpProbeError) as raised:
            context.probe.probe(_URL, config)
    assert_that(raised.value.refused, is_(True))
    return raised.value


def test_a_server_that_offers_oauth_and_got_no_token_says_how_to_proceed(monkeypatch):
    error = _refused_with(monkeypatch, FakeResponse(401, headers=_OAUTH_CHALLENGE), _NONE)

    assert_that(
        str(error),
        equal_to(
            "This server needs a sign-in (HTTP 401: No access token was provided in this request). "
            "Agent Barn does not support OAuth sign-in yet; if the server also accepts an API token, "
            "add it as the authentication."
        ),
    )


def test_a_refused_token_is_reported_in_the_servers_words(monkeypatch):
    challenge = {
        "WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token is not authorized", resource_metadata="x"'
    }

    error = _refused_with(monkeypatch, FakeResponse(401, headers=challenge), _BEARER)

    assert_that(
        str(error),
        equal_to(
            "The server refused the credentials (HTTP 401: Token is not authorized). "
            "If it accepts only an OAuth sign-in, Agent Barn cannot use it yet."
        ),
    )


def test_an_invalid_token_answered_with_400_is_a_refusal_not_unavailability(monkeypatch):
    challenge = {"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid token"'}

    error = _refused_with(monkeypatch, FakeResponse(400, headers=challenge), _BEARER)

    assert_that(str(error), equal_to("The server refused the credentials (HTTP 400: Invalid token)."))


def test_the_servers_reason_never_echoes_the_token(monkeypatch):
    challenge = {"WWW-Authenticate": 'Bearer error="invalid_token", error_description="bad token secret-token"'}

    error = _refused_with(monkeypatch, FakeResponse(401, headers=challenge), _BEARER)

    assert_that(str(error), is_not(contains_string("secret-token")))


def test_a_plain_bearer_challenge_is_an_ordinary_refusal(monkeypatch):
    error = _refused_with(monkeypatch, FakeResponse(401, headers={"WWW-Authenticate": 'Bearer realm="api"'}), _BEARER)

    assert_that(str(error), equal_to("The server refused the credentials (HTTP 401)."))


def test_a_redirect_is_not_followed(monkeypatch):
    redirect = FakeResponse(307, headers={"Location": "https://elsewhere.example.com/mcp"})
    with given([_public_dns(monkeypatch), _server_is(lambda method, body, headers: redirect)]) as context:
        with pytest.raises(McpProbeError, match="redirects are not followed"):
            context.probe.probe(_URL, _BEARER)

        assert_that(context.server.requests, has_length(1))


def test_a_json_rpc_error_is_reported_without_echoing_the_credential(monkeypatch):
    def answer(method, body, headers):
        return _json({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -1, "message": "bad token secret-token"}})

    with given([_public_dns(monkeypatch), _server_is(answer)]) as context:
        with pytest.raises(McpProbeError) as raised:
            context.probe.probe(_URL, _BEARER)

        assert_that(str(raised.value), contains_string("[REDACTED]"))
        assert_that(str(raised.value), is_not(contains_string("secret-token")))


def test_a_page_that_is_not_mcp_is_refused(monkeypatch):
    html = FakeResponse(200, b"<html>hello</html>", {"Content-Type": "text/html"})
    with given([_public_dns(monkeypatch), _server_is(lambda method, body, headers: html)]) as context:
        with pytest.raises(McpProbeError, match="MCP messages"):
            context.probe.probe(_URL, _BEARER)


@pytest.mark.parametrize("status", [404, 405])
def test_a_url_where_no_mcp_server_answers_says_so(monkeypatch, status: int):
    with given([_public_dns(monkeypatch), _server_is(lambda method, body, headers: FakeResponse(status))]) as context:
        with pytest.raises(McpProbeError, match=f"No MCP server answered at this URL \\(HTTP {status}\\)"):
            context.probe.probe(_URL, _BEARER)


def test_a_private_destination_is_refused_before_any_connection(monkeypatch):
    def private(host, port):
        raise RequestRefused("Destination resolves to a non-public address")

    monkeypatch.setattr(probe_module, "public_addresses", private)
    with given([_server_is(_well_behaved())]) as context:
        with pytest.raises(RequestRefused):
            context.probe.probe(_URL, _BEARER)

        assert_that(context.server.connected, empty())


def test_a_server_without_tools_is_reported_as_offering_none(monkeypatch):
    def answer(method, body, headers):
        if method == "DELETE" or body["method"] != "initialize":
            return FakeResponse(202)
        return _json(
            {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}}}
        )

    with given([_public_dns(monkeypatch), _server_is(answer)]) as context:
        result = context.probe.probe(_URL, {"auth": {"type": "none"}, "headers": []})

        assert_that(result.offers_tools, is_(False))
        assert_that(result.tools, empty())
        assert_that(analyse_tools("x", result, None, None).warnings, has_item(contains_string("does not offer tools")))


# --- what Agents will see -----------------------------------------------------


def _result(*names: str) -> ProbeResult:
    return ProbeResult(
        server_name=None,
        server_version=None,
        protocol_version="2025-11-25",
        offers_tools=True,
        tools=[ProbedTool(name=name, description=None) for name in names],
    )


def test_long_names_are_shortened_for_openclaw_and_flagged():
    long_name = "summarize_the_entire_knowledge_base_for_quarterly_review_x"

    analysis = analyse_tools("acme-knowledgebase", _result(long_name, "search"), None, None)

    assert_that(analysis.tools[0].openclaw_name, has_length(64))
    assert_that(analysis.tools[0].truncated, is_(True))
    assert_that(analysis.tools[1].truncated, is_(False))
    assert_that(analysis.warnings, contains_exactly(contains_string(long_name)))
    assert_that(analysis.collisions, empty())


def test_visible_tools_that_shorten_to_the_same_name_collide():
    prefix = "a" * 70

    analysis = analyse_tools("kb", _result(prefix + "_one", prefix + "_two"), None, None)

    assert_that(analysis.collisions, has_length(1))


def test_a_hidden_tool_does_not_collide():
    prefix = "a" * 70

    analysis = analyse_tools("kb", _result(prefix + "_one", prefix + "_two"), None, [prefix + "_two"])

    assert_that(analysis.collisions, empty())


def test_an_include_list_hides_the_rest_and_flags_names_the_server_lacks():
    analysis = analyse_tools("kb", _result("search", "delete"), ["search", "typo"], None)

    assert_that([(tool.name, tool.visible) for tool in analysis.tools], equal_to([("search", True), ("delete", False)]))
    assert_that(analysis.warnings, contains_exactly(contains_string("typo")))


def test_a_filter_that_hides_everything_is_flagged():
    analysis = analyse_tools("kb", _result("search"), None, ["search"])

    assert_that(analysis.warnings, has_item(contains_string("No tools are visible")))
