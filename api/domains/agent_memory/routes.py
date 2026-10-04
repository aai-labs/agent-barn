from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.agent_memory.models import (
    AgentMemoryGrantCreate,
    AgentMemoryGrantRead,
    AgentMemoryItemRead,
    AgentMemoryRead,
    AgentMemoryUpdate,
)
from api.domains.agent_memory.service import AgentMemoryService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems, Pagination

agent_memory_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/memory",
    tags=["agent-memory"],
)
memory_grants_router = APIRouter(
    prefix="/organizations/{organization_id}/memory-grants",
    tags=["agent-memory"],
)


@agent_memory_router.put("", response_model=AgentMemoryRead)
def set_agent_memory(
    agent_id: UUID,
    payload: AgentMemoryUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentMemoryService, Injected(AgentMemoryService)],
):
    return service.set_memory(agent_id, payload.enabled, context)


@agent_memory_router.get("/items", response_model=PaginatedItems[AgentMemoryItemRead])
def list_agent_memories(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentMemoryService, Injected(AgentMemoryService)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1, le=2000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 25,
):
    return service.list_memories(agent_id, search.strip() if search else None, Pagination(page, page_size), context)


@memory_grants_router.get("", response_model=list[AgentMemoryGrantRead])
def list_memory_grants(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentMemoryService, Injected(AgentMemoryService)],
):
    return service.list_grants(organization_id, context)


@memory_grants_router.post("", response_model=AgentMemoryGrantRead, status_code=status.HTTP_201_CREATED)
def create_memory_grant(
    organization_id: UUID,
    payload: AgentMemoryGrantCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentMemoryService, Injected(AgentMemoryService)],
):
    return service.create_grant(organization_id, payload, context)


@memory_grants_router.delete("/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_memory_grant(
    organization_id: UUID,
    grant_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentMemoryService, Injected(AgentMemoryService)],
) -> Response:
    service.revoke_grant(organization_id, grant_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
