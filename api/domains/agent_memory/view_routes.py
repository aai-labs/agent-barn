from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.concurrency import run_in_threadpool
from fastapi_injector import Injected

from api.domains.agent_memory.gateway_models import MemoryViewPage, MemoryViewQuery
from api.domains.agent_memory.view_capability import MemoryViewTarget
from api.domains.agent_memory.view_service import MemoryViewerService

memory_view_router = APIRouter()


def view_target(
    service: Annotated[MemoryViewerService, Injected(MemoryViewerService)],
    authorization: Annotated[str | None, Header()] = None,
) -> MemoryViewTarget:
    return service.authenticate(authorization)


@memory_view_router.get("/memories", response_model=MemoryViewPage)
async def list_memories(
    target: Annotated[MemoryViewTarget, Depends(view_target)],
    query: Annotated[MemoryViewQuery, Query()],
    service: Annotated[MemoryViewerService, Injected(MemoryViewerService)],
) -> MemoryViewPage:
    return await run_in_threadpool(service.list_memories, target, query)
