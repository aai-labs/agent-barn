"""Forwards an Agent's memory requests to Honcho (AF-338).

Agents hold a memory key, never a Honcho token: Honcho's tokens cannot be revoked,
so a copied one would outlive a stop, a group change or a budget suspension. Each
request is checked against the Agent as it is now, then forwarded with a token
scoped to its own pool, so Honcho still enforces the pool boundary if these rules
are ever wrong. Responses stream through: recall can take tens of seconds and the
SDKs can ask for server-sent events.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from injector import inject, noninjectable, singleton
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.agents.memory_access import AgentMemoryAccessService, MemoryAccessDenied, MemoryKeyRejected
from api.domains.memory_proxy.policy import MemoryRequestRefused, check_memory_request
from api.infrastructure.honcho.client import mint_workspace_token

logger = logging.getLogger(__name__)

# Longer than any runtime waits (Hermes 30s, OpenClaw 60s) so the runtime, not the
# proxy, decides when a slow recall has taken too long.
_UPSTREAM_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
_REQUEST_HEADERS = ("content-type", "accept")
_HOP_BY_HOP = frozenset({"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade"})


@singleton
class MemoryProxy:
    @inject
    @noninjectable("transport")
    def __init__(
        self,
        access: AgentMemoryAccessService,
        config: Config,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.access = access
        self.config = config
        self.transport = transport
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _http(self) -> httpx.AsyncClient:
        # One pooled client per event loop: a client is bound to the loop it was
        # created on.
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = httpx.AsyncClient(transport=self.transport, timeout=_UPSTREAM_TIMEOUT)
            self._client_loop = loop
        return self._client

    async def forward(self, request: Request, agent_id: str, path: str) -> Response:
        try:
            agent_uuid = UUID(agent_id)
        except ValueError:
            return _error(404, "Not found")
        key = _bearer(request.headers.get("authorization"))
        if key is None:
            return _error(401, "Missing memory key")
        try:
            workspace = await run_in_threadpool(self.access.authorize, agent_uuid, key)
        except MemoryKeyRejected:
            return _error(401, "Invalid memory key")
        except MemoryAccessDenied:
            return _error(403, "Memory is off for this agent")

        body = await request.body()
        try:
            check_memory_request(request.method, path, _parse_json(body), workspace)
        except MemoryRequestRefused as refused:
            return _error(403, str(refused))

        headers = {name: request.headers[name] for name in _REQUEST_HEADERS if name in request.headers}
        if self.config.honcho_jwt_secret:
            headers["authorization"] = f"Bearer {mint_workspace_token(self.config.honcho_jwt_secret, workspace)}"
        url = f"{self.config.honcho_base_url.rstrip('/')}/{path}"
        if request.url.query:
            url = f"{url}?{request.url.query}"

        client = self._http()
        try:
            upstream = await client.send(
                client.build_request(request.method, url, content=body, headers=headers), stream=True
            )
        except httpx.HTTPError:
            logger.warning("Memory proxy could not reach Honcho for Agent %s", agent_uuid)
            return _error(502, "Memory is unavailable right now")
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP},
            background=BackgroundTask(upstream.aclose),
        )


def _bearer(header: str | None) -> str | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def _parse_json(body: bytes) -> Any:
    """The body as JSON, or the raw text when it is not JSON — which the policy
    treats as unreadable wherever the body decides the outcome."""
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body.decode(errors="replace")


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})
