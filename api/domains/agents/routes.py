from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.agents.models import (
    AgentCreate,
    AgentFilter,
    AgentRead,
    AgentUpdate,
    get_agent_filter,
)
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems, Pagination

agents_router = APIRouter(prefix="/agents", tags=["agents"])


@agents_router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(
    data: AgentCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.create_agent(data, context)


@agents_router.get("", response_model=PaginatedItems[AgentRead])
def list_agents(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    agent_filter: Annotated[AgentFilter, Depends(get_agent_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_agents(
        agent_filter=agent_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@agents_router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.get_agent(agent_id, context)


@agents_router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.update_agent(agent_id, data, context)


@agents_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    service.delete_agent(agent_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agents_router.post("/{agent_id}/start", response_model=AgentRead)
def start_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.start_agent(agent_id, context)


@agents_router.post("/{agent_id}/stop", response_model=AgentRead)
def stop_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.stop_agent(agent_id, context)
