import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi_injector import Injected

from api.domains.agent_memory.gateway_models import MemoryAccess
from api.domains.agent_memory.gateway_service import MemoryGatewayService

memory_gateway_router = APIRouter()


def memory_access(
    service: Annotated[MemoryGatewayService, Injected(MemoryGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> MemoryAccess:
    return service.authenticate(authorization)


@memory_gateway_router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def memory_request(
    path: str,
    request: Request,
    access: Annotated[MemoryAccess, Depends(memory_access)],
    service: Annotated[MemoryGatewayService, Injected(MemoryGatewayService)],
) -> Response:
    payload = None
    if service.accepts_payload(request.method, path):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2 * 1024 * 1024:
                raise HTTPException(413, "Agent Memory request is too large.")
        try:
            payload = json.loads(body) if body else None
        except ValueError, UnicodeDecodeError:
            raise HTTPException(422, "Invalid Agent Memory request.") from None
    result = await run_in_threadpool(service.forward, access, request.method, path, payload)
    return Response(content=result.content, status_code=result.status_code, media_type="application/json")
