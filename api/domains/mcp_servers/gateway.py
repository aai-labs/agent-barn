"""The credential gateway's MCP route: the only way an Agent reaches an Organization MCP Server.

The pod holds one per-start token and the server's gateway URL. For every request the gateway:

1. resolves the token to the running Agent generation it was issued to;
2. finds the server named in the path among the servers that Agent may use now, in its own
   Organization only;
3. enforces the server's tool filter;
4. replaces the token with the server's credential and relays the exchange, streaming the
   answer back, at a pinned public address, with no redirects.

Because all of this happens per request, disabling, detaching, deleting, re-pointing or
rotating a server takes effect on the Agent's next request.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi_injector import Injected
from injector import inject, singleton
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.custom_api.request import RequestRefused
from api.domains.mcp_servers.broker import CredentialUnavailable, McpCredentialBroker
from api.domains.mcp_servers.models import AgentMcpGatewayToken, OrganizationMcpServer
from api.domains.mcp_servers.repository import McpServerRepository
from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 1024 * 1024
#: A `tools/list` answer is read whole so hidden tools can be removed from it.
MAX_TOOLS_LIST_BYTES = 5 * 1024 * 1024
MAX_STREAM_BYTES = 10 * 1024 * 1024
MAX_STREAM_SECONDS = 600
#: Per server and gateway process, so one slow server cannot hold every connection.
MAX_CONCURRENT_PER_SERVER = 8
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

#: Shown to the model verbatim by OpenClaw, so it names nothing internal.
UNAVAILABLE = "This MCP server is no longer available to this Agent."
_INVALID_CREDENTIAL = "Invalid MCP gateway credential"
_FORWARDED_REQUEST_HEADERS = ("mcp-session-id", "mcp-protocol-version", "accept", "content-type", "last-event-id")
_FORWARDED_RESPONSE_HEADERS = ("content-type", "mcp-session-id")
_SERVER_UNAVAILABLE = -32001
_INVALID_PARAMS = -32602


def _rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def tool_visible(server: OrganizationMcpServer, name: object) -> bool:
    if not isinstance(name, str):
        return False
    if server.tool_include is not None:
        return name in server.tool_include
    return server.tool_exclude is None or name not in server.tool_exclude


def _filter_result(message: dict, request_id: Any, server: OrganizationMcpServer) -> dict:
    result = message.get("result")
    if message.get("id") == request_id and isinstance(result, dict) and isinstance(result.get("tools"), list):
        tools = [tool for tool in result["tools"] if isinstance(tool, dict) and tool_visible(server, tool.get("name"))]
        return {**message, "result": {**result, "tools": tools}}
    return message


def filter_tools_list(content: bytes, content_type: str, request_id: Any, server: OrganizationMcpServer) -> bytes:
    """Removes hidden tools from a `tools/list` answer in either framing Streamable HTTP uses."""
    if content_type.split(";")[0].strip().lower() == "text/event-stream":
        events = []
        for event in content.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n\n"):
            if not event.strip():
                continue
            other = [line for line in event.split("\n") if not line.startswith("data:")]
            data = "\n".join(line[5:].removeprefix(" ") for line in event.split("\n") if line.startswith("data:"))
            try:
                message = json.loads(data) if data else None
            except ValueError:
                message = None
            if isinstance(message, dict):
                data = json.dumps(_filter_result(message, request_id, server))
            events.append("\n".join([*other, *(f"data: {line}" for line in data.split("\n"))]) if data else event)
        return ("\n\n".join(events) + "\n\n").encode()
    try:
        message = json.loads(content)
    except ValueError:
        return content
    return json.dumps(_filter_result(message, request_id, server)).encode() if isinstance(message, dict) else content


def redact(data: bytes, sensitive: list[bytes]) -> bytes:
    for value in sensitive:
        data = data.replace(value, b"[REDACTED]")
    return data


@dataclass(frozen=True)
class _Upstream:
    server: OrganizationMcpServer
    url: str
    headers: dict[str, str]
    extensions: dict[str, str]
    sensitive: list[bytes]
    oauth_credential_id: UUID | None = None


@inject
@singleton
class McpGateway:
    def __init__(self, repository: McpServerRepository, config: Config, broker: McpCredentialBroker) -> None:
        self.repository = repository
        self.config = config
        self.broker = broker
        self._slots: dict[UUID, asyncio.Semaphore] = {}

    # --- resolution (blocking; run in the thread pool) -------------------------

    def authorize(self, authorization: str | None) -> AgentMcpGatewayToken | None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return self.repository.authorize_gateway_token(hashlib.sha256(token.strip().encode()).hexdigest())

    def server_for(self, agent_id: UUID, identifier: str) -> OrganizationMcpServer | None:
        return next(
            (server for server in self.repository.effective_for_agent(agent_id) if server.identifier == identifier),
            None,
        )

    def upstream(self, server: OrganizationMcpServer, agent_id: UUID) -> _Upstream:
        """The Agent's own credential if it has one, else the Organization's.

        Raises `CredentialUnavailable` when there is none to use (an OAuth server nobody has
        signed in to, or an expired sign-in), and `NonPublicDestination` or `RequestRefused`
        for a server it must not contact.
        """
        credential = self.broker.resolve(server, agent_id)
        pinned = pin_to_public_address(server.url)
        return _Upstream(
            server=server,
            url=pinned.url,
            headers={**pinned.headers, **credential.headers},
            extensions=pinned.extensions,
            sensitive=sorted({value.encode() for value in credential.sensitive if value}, key=len, reverse=True),
            oauth_credential_id=credential.oauth_credential_id,
        )

    # --- the exchange ------------------------------------------------------------

    async def handle(self, identifier: str, request: Request) -> Response:
        token = await run_in_threadpool(self.authorize, request.headers.get("authorization"))
        if token is None:
            logger.warning("MCP gateway refused a request for %s: invalid or stale credential", identifier)
            return JSONResponse({"error": _INVALID_CREDENTIAL}, status_code=403)
        message: dict | None = None
        body = b""
        if request.method == "POST":
            body = await _read_limited(request, MAX_REQUEST_BYTES)
            if body is None:
                return JSONResponse({"error": "Request larger than 1 MiB"}, status_code=413)
            try:
                parsed = json.loads(body)
            except ValueError:
                return JSONResponse({"error": "Request is not JSON-RPC"}, status_code=400)
            if not isinstance(parsed, dict):
                # The current MCP revision has no batches; refusing them keeps the tool check whole.
                return JSONResponse({"error": "JSON-RPC batches are not supported"}, status_code=400)
            message = parsed
        request_id = message.get("id") if message else None
        server = await run_in_threadpool(self.server_for, token.agent_id, identifier)
        if server is None:
            logger.warning(
                "MCP gateway refused Agent %s (Organization %s): server %s is not available to it",
                token.agent_id,
                token.organization_id,
                identifier,
            )
            if request_id is not None:
                return _rpc_error(request_id, _SERVER_UNAVAILABLE, UNAVAILABLE)
            return JSONResponse({"error": UNAVAILABLE}, status_code=403)
        if request.method in {"GET", "HEAD"}:
            # The server-to-client stream is optional in Streamable HTTP; not offering it keeps
            # idle long-lived connections out of the gateway.
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})
        method = message.get("method") if message else None
        if method == "tools/call":
            params = message.get("params") if message and isinstance(message.get("params"), dict) else {}
            if not tool_visible(server, params.get("name")):
                logger.warning(
                    "MCP gateway refused Agent %s a hidden tool on server %s", token.agent_id, server.identifier
                )
                return _rpc_error(request_id, _INVALID_PARAMS, "Tool not available")
        slot = self._slots.setdefault(server.id, asyncio.Semaphore(MAX_CONCURRENT_PER_SERVER))
        if slot.locked():
            return JSONResponse({"error": "MCP server busy"}, status_code=503, headers={"Retry-After": "5"})
        await slot.acquire()
        try:
            upstream = await run_in_threadpool(self.upstream, server, token.agent_id)
        except CredentialUnavailable as exc:
            slot.release()
            logger.warning(
                "MCP gateway has no usable credential for Agent %s on server %s", token.agent_id, server.identifier
            )
            if request_id is not None:
                return _rpc_error(request_id, _SERVER_UNAVAILABLE, str(exc))
            return JSONResponse({"error": str(exc)}, status_code=403)
        except NonPublicDestination, RequestRefused, KeyError, TypeError, ValueError:
            slot.release()
            logger.warning("MCP gateway could not use server %s's configuration", server.identifier)
            return JSONResponse({"error": "MCP server unavailable"}, status_code=502)
        except BaseException:
            slot.release()
            raise
        return await self._relay(request, upstream, body, method, request_id, slot)

    async def _relay(
        self,
        request: Request,
        upstream: _Upstream,
        body: bytes,
        method: str | None,
        request_id: Any,
        slot: asyncio.Semaphore,
    ) -> Response:
        headers = dict(upstream.headers)
        for name in _FORWARDED_REQUEST_HEADERS:
            if value := request.headers.get(name):
                headers[name] = value
        client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False)
        try:
            response = await client.send(
                client.build_request(
                    request.method,
                    upstream.url,
                    content=body or None,
                    headers=headers,
                    extensions=upstream.extensions,
                ),
                stream=True,
            )
        except httpx.HTTPError:
            await client.aclose()
            slot.release()
            return JSONResponse({"error": "MCP server unreachable"}, status_code=502)
        except BaseException:
            await client.aclose()
            slot.release()
            raise
        if response.status_code == 401 and upstream.oauth_credential_id is not None:
            # The server no longer accepts this access token; the next request refreshes it.
            await run_in_threadpool(self.broker.retire_access_token, upstream.oauth_credential_id)
        if 300 <= response.status_code < 400:
            await response.aclose()
            await client.aclose()
            slot.release()
            return JSONResponse({"error": "MCP server redirected; redirects are not followed"}, status_code=502)
        forwarded = {name: value for name in _FORWARDED_RESPONSE_HEADERS if (value := response.headers.get(name))}
        if method == "tools/list" and response.status_code == 200:
            try:
                content = await _read_stream(response, MAX_TOOLS_LIST_BYTES)
            finally:
                await response.aclose()
                await client.aclose()
                slot.release()
            if content is None:
                return JSONResponse({"error": "MCP server's tool list is too large"}, status_code=502)
            filtered = filter_tools_list(content, forwarded.get("content-type", ""), request_id, upstream.server)
            return Response(redact(filtered, upstream.sensitive), status_code=200, headers=forwarded)
        return StreamingResponse(
            _stream(response, client, slot, upstream.sensitive),
            status_code=response.status_code,
            headers=forwarded,
        )


async def _read_limited(request: Request, limit: int) -> bytes | None:
    content = b""
    async for chunk in request.stream():
        content += chunk
        if len(content) > limit:
            return None
    return content


async def _read_stream(response: httpx.Response, limit: int) -> bytes | None:
    content = b""
    async for chunk in response.aiter_bytes():
        content += chunk
        if len(content) > limit:
            return None
    return content


async def _stream(
    response: httpx.Response, client: httpx.AsyncClient, slot: asyncio.Semaphore, sensitive: list[bytes]
) -> AsyncIterator[bytes]:
    """Relays the answer line by line, so a credential echoed upstream is redacted whole."""
    deadline = time.monotonic() + MAX_STREAM_SECONDS
    total = 0
    pending = b""
    try:
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_STREAM_BYTES or time.monotonic() > deadline:
                logger.warning("MCP gateway cut a stream at its size or time limit")
                return
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for line in lines:
                yield redact(line, sensitive) + b"\n"
        if pending:
            yield redact(pending, sensitive)
    finally:
        await response.aclose()
        await client.aclose()
        slot.release()


mcp_gateway_router = APIRouter()


@mcp_gateway_router.api_route("/mcp/{identifier}", methods=["GET", "HEAD", "POST", "DELETE"])
async def relay_mcp(
    identifier: str, request: Request, gateway: Annotated[McpGateway, Injected(McpGateway)]
) -> Response:
    return await gateway.handle(identifier, request)
